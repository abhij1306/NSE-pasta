from nse_pasta import cli, layout


def test_two_pulls_never_run_at_once(tmp_path, capsys):
    folder = layout.Layout(tmp_path)
    with layout.locked(folder):
        assert cli.run(["--data", str(tmp_path), "parse"]) == 1
    assert "in use by another pasta process" in capsys.readouterr().err


def test_parse_needs_a_universe(tmp_path, capsys):
    assert cli.run(["--data", str(tmp_path), "parse"]) == 1
    assert "no universe yet" in capsys.readouterr().err


def test_a_bad_settings_file_is_exit_2(tmp_path):
    (tmp_path / "pasta.toml").write_text("[run]\nsource = 'bse'\n", encoding="utf-8")
    assert cli.run(["--data", str(tmp_path), "status"]) == 2


def test_config_init_then_status(tmp_path, capsys):
    assert cli.run(["--data", str(tmp_path), "config", "init"]) == 0
    assert cli.run(["--data", str(tmp_path), "config", "init"]) == 1  # never over a file
    assert cli.run(["--data", str(tmp_path), "status"]) == 0
    assert "empty" in capsys.readouterr().out
