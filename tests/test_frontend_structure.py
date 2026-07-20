from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendStructureTests(unittest.TestCase):
    def test_backups_live_under_system_view(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn('data-view="system"', html)
        system = re.search(r'<section id="system" class="view">(.*?)</section>', html, re.S)
        settings = re.search(r'<section id="settings" class="view">(.*?)</section>', html, re.S)

        self.assertIsNotNone(system)
        self.assertIsNotNone(settings)
        self.assertIn('id="create-backup"', system.group(1))
        self.assertIn('id="import-backup"', system.group(1))
        self.assertIn('id="backup-file-input"', system.group(1))
        self.assertNotIn('id="create-backup"', settings.group(1))
        self.assertNotIn('id="import-backup"', settings.group(1))

    def test_frontend_copy_is_not_english_only(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("Bazarr English subtitles", html)
        self.assertNotIn("Local English Subtitles", html)
        self.assertNotIn("English subtitles to Gemini", app_js)

    def test_secret_fields_have_masks_and_test_buttons(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="test-bazarr-key"', html)
        self.assertIn('id="test-gemini-key"', html)
        self.assertIn('id="test-gemini-key2"', html)
        self.assertIn('id="test-tmdb-key"', html)
        self.assertIn('const SECRET_MASK = "**********";', app_js)
        self.assertIn("/api/test-connection", app_js)

    def test_logs_have_clear_button_and_gst_model_uses_select(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="clear-logs"', html)
        self.assertIn('id="gst-model-select"', html)
        self.assertIn('id="job-settle-seconds-input"', html)
        self.assertIn('id="gst-token-report-input"', html)
        self.assertIn("Token report", html)
        self.assertNotIn('id="gst-token-stats-input"', html)
        self.assertNotIn("Token stats", html)
        self.assertNotIn('id="gst-model-input"', html)
        self.assertIn("/api/logs/clear", app_js)
        self.assertIn("/api/gemini-models", app_js)
        self.assertIn("job_settle_seconds", app_js)
        self.assertIn("gst_token_report", app_js)
        self.assertNotIn("gst_token_stats", app_js)

    def test_backup_ui_supports_download_and_import(self):
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("/api/backups/download", app_js)
        self.assertIn("/api/backups/import", app_js)
        self.assertIn("importBackup", app_js)

    def test_navigation_uses_url_hash_and_has_no_refresh_button(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn('id="refresh"', html)
        self.assertIn("window.location.hash", app_js)
        self.assertIn('window.addEventListener("hashchange"', app_js)
        self.assertIn("switchView(viewFromHash())", app_js)


class BackendPackageBoundaryTests(unittest.TestCase):
    def test_worker_reexports_split_package_helpers(self):
        import worker
        from gst_worker import backups, bazarr, config, http, queue, subtitles, tmdb, translation

        self.assertIs(worker.normalize_app_config, config.normalize_app_config)
        self.assertIs(worker.create_backup, backups.create_backup)
        self.assertIs(worker.target_output_path, subtitles.target_output_path)
        self.assertIs(worker.enqueue_translation_jobs, queue.enqueue_translation_jobs)
        self.assertIs(worker.HTTPClient, http.HTTPClient)
        self.assertIs(worker.build_tmdb_description, tmdb.build_tmdb_description)
        self.assertIs(worker.refresh_bazarr, bazarr.refresh_bazarr)
        self.assertIs(worker.build_gst_command, translation.build_gst_command)


class DeploymentConfigTests(unittest.TestCase):
    def test_compose_uses_6789_inside_and_outside_container(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        worker_py = (ROOT / "worker.py").read_text(encoding="utf-8")

        self.assertIn("name: gemini-srt-translator-bazarr", compose)
        self.assertIn("WEB_PORT: 6789", compose)
        self.assertIn("- 6789:6789", compose)
        self.assertNotIn("WEB_PORT=", env_example)
        self.assertNotIn("HOST_PORT=", env_example)
        self.assertIn('os.getenv("WEB_PORT", "6789")', worker_py)
        self.assertNotIn(":8080", compose)

    def test_default_state_dir_mounts_project_root_not_nested_state_dir(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn("${WORKER_STATE_DIR:-/opt/docker/gemini-srt-translator-bazarr}:/state", compose)
        self.assertNotIn("${WORKER_STATE_DIR:-/opt/docker/gemini-srt-translator-bazarr/state}:/state", compose)
        self.assertIn("WORKER_STATE_DIR=/opt/docker/gemini-srt-translator-bazarr", env_example)
        self.assertNotIn("WORKER_STATE_DIR=/opt/docker/gemini-srt-translator-bazarr/state", env_example)

    def test_queue_mount_is_outside_worker_state_mount(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        worker_py = (ROOT / "worker.py").read_text(encoding="utf-8")

        self.assertIn("QUEUE_DIR: /queue", compose)
        self.assertIn("${BAZARR_POSTPROCESS_DIR:-/opt/docker/bazarr/postprocess}/queue:/queue", compose)
        self.assertNotIn("QUEUE_DIR: /state/queue", compose)
        self.assertNotIn(":/state/queue", compose)
        self.assertIn('os.getenv("QUEUE_DIR", "/queue")', worker_py)

    def test_docker_build_skips_ffmpeg_by_default_after_upstream_fix(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('"gemini-srt-translator>=3.5.9,<4"', pyproject)
        self.assertIn("uv sync --locked --no-dev", dockerfile)
        self.assertIn("ARG INSTALL_FFMPEG=false", dockerfile)
        self.assertIn("apt-get install -y --no-install-recommends ffmpeg", dockerfile)
        self.assertIn("INSTALL_FFMPEG: ${INSTALL_FFMPEG:-false}", compose)
        self.assertIn("INSTALL_FFMPEG=false", env_example)


if __name__ == "__main__":
    unittest.main()
