-- Schema token is replaced only by psycopg.sql.Identifier from the installer.
ALTER TABLE __SCHEMA__.companies ADD COLUMN network_revision bigint NOT NULL DEFAULT 0;
CREATE TABLE __SCHEMA__._network_logins (
    db_login name PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES __SCHEMA__.users(id) ON DELETE CASCADE
);
CREATE TABLE __SCHEMA__._network_company_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id bigint NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    user_id bigint NOT NULL,
    user_name text NOT NULL,
    db_login name NOT NULL,
    request_id uuid NOT NULL,
    previous jsonb,
    current jsonb NOT NULL,
    UNIQUE(db_login,request_id)
);
CREATE TABLE __SCHEMA__._network_operations (
    db_login name NOT NULL,
    request_id uuid NOT NULL,
    request jsonb NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY(db_login,request_id)
);

CREATE FUNCTION __SCHEMA__.network_claims(required_level integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE account record; permissions jsonb; permission integer;
BEGIN
    SELECT u.id,u.name,u.active,u.tab_permissions INTO account
      FROM __SCHEMA__._network_logins l JOIN __SCHEMA__.users u ON u.id=l.user_id
      WHERE l.db_login=session_user FOR SHARE OF l,u;
    IF NOT FOUND OR account.active IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION USING ERRCODE='P2001', MESSAGE='Přístup k síťovému pilotu není povolen.';
    END IF;
    IF lower(btrim(account.name))='admin' THEN permission:=2;
    ELSE
        BEGIN
            permissions:=coalesce(nullif(account.tab_permissions,''),'{}')::jsonb;
            IF jsonb_typeof(permissions)<>'object' OR EXISTS(
                SELECT 1 FROM jsonb_each(permissions) e WHERE e.value NOT IN ('0'::jsonb,'1'::jsonb,'2'::jsonb)
            ) THEN RAISE EXCEPTION 'invalid'; END IF;
            permission:=coalesce((permissions->>'companies')::integer,2);
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION USING ERRCODE='P2001', MESSAGE='Neplatné nastavení oprávnění uživatele.';
        END;
    END IF;
    IF required_level IS NULL OR required_level<0 OR required_level>2 OR permission<required_level THEN
        RAISE EXCEPTION USING ERRCODE='P2001', MESSAGE='Nemáte oprávnění pro tuto operaci se společnostmi.';
    END IF;
    RETURN jsonb_build_object('user_id',account.id,'name',account.name,'login',session_user,'companies',permission);
END $$;

CREATE FUNCTION __SCHEMA__.network_identity() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN RETURN __SCHEMA__.network_claims(0); END $$;

CREATE FUNCTION __SCHEMA__.network_companies(p_query text,p_limit integer,p_offset integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE actor jsonb; result jsonb; total bigint;
BEGIN
    actor:=__SCHEMA__.network_claims(1);
    IF p_query IS NULL OR length(p_query)>200 OR p_limit IS NULL OR p_limit<1 OR p_limit>200
       OR p_offset IS NULL OR p_offset<0 THEN
        RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Neplatný filtr nebo stránka.';
    END IF;
    SELECT count(*) INTO total FROM __SCHEMA__.companies c
      WHERE p_query='' OR strpos(lower(coalesce(c.official_name,'')||' '||coalesce(c.short_name,'')||' '||coalesce(c.ico,'')),lower(p_query))>0;
    SELECT coalesce(jsonb_agg(to_jsonb(c)),'[]'::jsonb) INTO result FROM (
      SELECT id,short_name,official_name,ico,address,is_customer,is_supplier,active,network_revision
      FROM __SCHEMA__.companies
      WHERE p_query='' OR strpos(lower(coalesce(official_name,'')||' '||coalesce(short_name,'')||' '||coalesce(ico,'')),lower(p_query))>0
      ORDER BY lower(coalesce(nullif(official_name,''),short_name)),id LIMIT p_limit OFFSET p_offset
    ) c;
    RETURN jsonb_build_object('items',result,'total',total,'identity',actor);
END $$;

CREATE FUNCTION __SCHEMA__.network_company(p_id bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE result jsonb; actor jsonb;
BEGIN
    actor:=__SCHEMA__.network_claims(1);
    SELECT to_jsonb(c) INTO result FROM __SCHEMA__.companies c WHERE c.id=p_id;
    IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='P2003', MESSAGE='Společnost už neexistuje.'; END IF;
    RETURN jsonb_build_object('company',result,'identity',actor);
END $$;

CREATE FUNCTION __SCHEMA__.network_save_company(p_id bigint,p_revision bigint,p_values jsonb,p_request uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE actor jsonb; before_row jsonb; after_row jsonb; merged jsonb; request jsonb; saved record; item record; new_id bigint;
BEGIN
    actor:=__SCHEMA__.network_claims(2);
    IF p_request IS NULL OR p_values IS NULL OR jsonb_typeof(p_values)<>'object' OR p_revision IS NULL OR p_revision<0 THEN
        RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Neplatné údaje společnosti.';
    END IF;
    request:=jsonb_build_object('id',p_id,'revision',p_revision,'values',p_values);
    -- A request UUID is kept across a manual retry after an uncertain connection.
    -- The server serializes duplicates and never executes the same write twice.
    PERFORM pg_advisory_xact_lock(hashtextextended(session_user||':'||p_request::text,0));
    SELECT o.request,o.result INTO saved FROM __SCHEMA__._network_operations o
      WHERE o.db_login=session_user AND o.request_id=p_request;
    IF FOUND THEN
        IF saved.request IS DISTINCT FROM request THEN
            RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Identifikátor uložení byl použit pro jiná data.';
        END IF;
        RETURN saved.result;
    END IF;
    FOR item IN SELECT * FROM jsonb_each(p_values) LOOP
        IF item.key NOT IN ('short_name','official_name','ico','dic','address','web','note','active','is_customer','is_supplier') THEN
            RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Nepovolené pole společnosti.';
        END IF;
        IF item.key IN ('active','is_customer','is_supplier') THEN
            IF item.value NOT IN ('0'::jsonb,'1'::jsonb) THEN
                RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Neplatný stav společnosti.';
            END IF;
        ELSIF jsonb_typeof(item.value)<>'string' OR length(item.value #>> '{}')>20000 THEN
            RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Neplatný text společnosti.';
        END IF;
    END LOOP;
    IF p_id IS NOT NULL THEN
        SELECT to_jsonb(c) INTO before_row FROM __SCHEMA__.companies c WHERE c.id=p_id FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='P2003', MESSAGE='Společnost už neexistuje.'; END IF;
        IF (before_row->>'network_revision')::bigint<>p_revision THEN
            RAISE EXCEPTION USING ERRCODE='P2002', MESSAGE='Společnost mezitím změnil jiný uživatel. Načtěte aktuální údaje.';
        END IF;
        merged:=before_row||p_values;
    ELSE
        IF p_revision<>0 THEN RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Neplatná verze nové společnosti.'; END IF;
        merged:='{"short_name":"","official_name":"","ico":"","dic":"","address":"","web":"","note":"","active":1,"is_customer":1,"is_supplier":0}'::jsonb||p_values;
    END IF;
    IF btrim(coalesce(nullif(merged->>'official_name',''),merged->>'short_name',''))='' THEN
        RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='Vyplňte název společnosti.';
    END IF;
    IF p_id IS NULL THEN
        INSERT INTO __SCHEMA__.companies(short_name,official_name,ico,dic,address,web,note,active,is_customer,is_supplier,date_created,network_revision)
          VALUES(coalesce(nullif(merged->>'short_name',''),merged->>'official_name'),merged->>'official_name',merged->>'ico',merged->>'dic',
                 merged->>'address',merged->>'web',merged->>'note',(merged->>'active')::bigint,(merged->>'is_customer')::bigint,
                 (merged->>'is_supplier')::bigint,to_char(current_timestamp,'YYYY-MM-DD'),1) RETURNING id INTO new_id;
    ELSE
        new_id:=p_id;
        UPDATE __SCHEMA__.companies SET short_name=merged->>'short_name',official_name=merged->>'official_name',ico=merged->>'ico',dic=merged->>'dic',
          address=merged->>'address',web=merged->>'web',note=merged->>'note',active=(merged->>'active')::bigint,
          is_customer=(merged->>'is_customer')::bigint,is_supplier=(merged->>'is_supplier')::bigint,network_revision=network_revision+1
          WHERE id=p_id;
    END IF;
    SELECT to_jsonb(c) INTO after_row FROM __SCHEMA__.companies c WHERE c.id=new_id;
    INSERT INTO __SCHEMA__._network_company_audit(company_id,user_id,user_name,db_login,request_id,previous,current)
      VALUES(new_id,(actor->>'user_id')::bigint,actor->>'name',session_user,p_request,before_row,after_row);
    INSERT INTO __SCHEMA__._network_operations(db_login,request_id,request,result) VALUES(session_user,p_request,request,after_row);
    RETURN after_row;
END $$;

CREATE FUNCTION __SCHEMA__.network_company_history(p_id bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE result jsonb;
BEGIN
    PERFORM __SCHEMA__.network_claims(1);
    SELECT coalesce(jsonb_agg(to_jsonb(a)),'[]'::jsonb) INTO result FROM (
      SELECT id,changed_at,user_name,db_login,previous,current FROM __SCHEMA__._network_company_audit
        WHERE company_id=p_id ORDER BY id DESC LIMIT 100
    ) a;
    RETURN result;
END $$;

CREATE FUNCTION __SCHEMA__.network_operation(p_request uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE result jsonb;
BEGIN
    PERFORM __SCHEMA__.network_claims(1);
    SELECT o.result INTO result FROM __SCHEMA__._network_operations o
      WHERE o.db_login=session_user AND o.request_id=p_request;
    RETURN result;
END $$;
