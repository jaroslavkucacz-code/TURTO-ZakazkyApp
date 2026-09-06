from pathlib import Path
import hashlib
p=Path('scripts/validate-7900-runtime-integration.py')
s=p.read_text(encoding='utf-8')
s=s.replace('sys.path.insert(0,str(source));sys.path.insert(0,str(source.parent));os.chdir(source)', '''sys.path.insert(0,str(source));os.chdir(source)
        # publish-update.sh explicitly copies this one root module into the
        # release; do not prioritize the entire repository over current source.
        import importlib.util
        baseline_path = source.parent / 'post_baseline.py'
        spec = importlib.util.spec_from_file_location('post_baseline', baseline_path)
        baseline = importlib.util.module_from_spec(spec)
        sys.modules['post_baseline'] = baseline
        spec.loader.exec_module(baseline)''',1)
s=s.replace('M.ensure_schema();runtime_bootstrap.apply_all(M);M.ensure_schema();M.ensure_test_user()', '''M.ensure_schema();runtime_bootstrap.apply_all(M);M.ensure_schema();M.ensure_test_user()
        # The installer copies modules from source; only post_baseline comes
        # from repository root. Historical root duplicates must not be loaded.
        assert Path(M.__file__).resolve().parent == source
        layer_names = (*runtime_bootstrap.EARLY_LAYERS, *runtime_bootstrap.LATE_LAYERS,
                       'runtime_bootstrap', 'v644_default_date_sort', 'v631_diskdrop', 'crm_price_lists')
        for name in layer_names:
            assert Path(sys.modules[name].__file__).resolve().is_relative_to(source), name
        assert Path(sys.modules['post_baseline'].__file__).resolve() == baseline_path''',1)
p.write_text(s,encoding='utf-8')
assert hashlib.sha256(p.read_bytes()).hexdigest() == 'dd0f2c1d5d6dfbee3d21073396834e73cdc93586e3ca9f06bf205a540b5038ce'
print('Verified integration test imports precisely the modules selected by publish-update.sh')
