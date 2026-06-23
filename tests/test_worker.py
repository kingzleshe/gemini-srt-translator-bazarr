import json
import io
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import worker


class FakeHTTP:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def get_json(self, url, params=None, headers=None):
        self.calls.append(("GET", url, params or {}, headers or {}))
        key = (url, tuple(sorted((params or {}).items())))
        return self.responses[key]

    def request_json(self, method, url, params=None, headers=None):
        self.calls.append((method, url, params or {}, headers or {}))
        return {"ok": True}


class WorkerTests(unittest.TestCase):
    def test_zh_output_path_replaces_english_language_code(self):
        self.assertEqual(
            worker.zh_output_path("/media/Movie/Test.Movie.en.srt"),
            "/media/Movie/Test.Movie.zh.srt",
        )
        self.assertEqual(
            worker.zh_output_path("/media/Show/Episode.eng.srt"),
            "/media/Show/Episode.zh.srt",
        )
        self.assertEqual(
            worker.zh_output_path("/media/Show/Episode.en.hi.srt"),
            "/media/Show/Episode.zh.hi.srt",
        )

    def test_target_output_path_replaces_english_with_configured_target(self):
        self.assertEqual(
            worker.target_output_path("/media/Movie/Test.Movie.en.srt", "zt"),
            "/media/Movie/Test.Movie.zt.srt",
        )
        self.assertEqual(
            worker.target_output_path("/media/Show/Episode.eng.srt", "ja"),
            "/media/Show/Episode.ja.srt",
        )

    def test_target_output_path_replaces_configured_source_language(self):
        self.assertEqual(
            worker.target_output_path("/media/Movie/Test.Movie.ja.srt", "zh", source_code="ja"),
            "/media/Movie/Test.Movie.zh.srt",
        )
        self.assertEqual(
            worker.target_output_path("/media/Show/Episode.ko.sdh.srt", "en", source_code="ko"),
            "/media/Show/Episode.en.sdh.srt",
        )

    def test_enabled_source_languages_default_to_english(self):
        self.assertEqual(
            worker.enabled_source_languages({}),
            [{"code": "en", "language": "English", "enabled": True}],
        )
        self.assertEqual(
            worker.enabled_source_languages(
                {
                    "source_languages": [
                        {"code": "en", "language": "English", "enabled": False},
                        {"code": "ja", "language": "Japanese", "enabled": True},
                    ]
                }
            ),
            [{"code": "ja", "language": "Japanese", "enabled": True}],
        )

    def test_enabled_target_languages_default_to_simplified_chinese(self):
        self.assertEqual(
            worker.enabled_target_languages({}),
            [{"code": "zh", "language": "Simplified Chinese", "enabled": True}],
        )
        self.assertEqual(
            worker.enabled_target_languages(
                {
                    "target_languages": [
                        {"code": "zh", "language": "Simplified Chinese", "enabled": False},
                        {"code": "zt", "language": "Traditional Chinese", "enabled": True},
                    ]
                }
            ),
            [{"code": "zt", "language": "Traditional Chinese", "enabled": True}],
        )

    def test_supported_target_languages_normalizes_bazarr_languages(self):
        http = FakeHTTP(
            {
                (
                    "http://bazarr:6767/api/system/languages",
                    (),
                ): [
                    {"name": "Chinese Simplified", "code2": "zh", "code3": "zho", "enabled": True},
                    {"name": "English", "code2": "en", "code3": "eng", "enabled": True},
                    {"name": "Japanese", "code2": "ja", "code3": "jpn", "enabled": False},
                ]
            }
        )

        languages = worker.supported_languages(http, "http://bazarr:6767", "key")

        self.assertEqual(
            languages,
            [
                {
                    "code": "zh",
                    "code3": "zho",
                    "name": "Chinese Simplified",
                    "language": "Simplified Chinese",
                    "enabled_in_bazarr": True,
                },
                {
                    "code": "en",
                    "code3": "eng",
                    "name": "English",
                    "language": "English",
                    "enabled_in_bazarr": True,
                },
                {
                    "code": "ja",
                    "code3": "jpn",
                    "name": "Japanese",
                    "language": "Japanese",
                    "enabled_in_bazarr": False,
                },
            ],
        )

    def test_save_app_config_writes_worker_and_postprocess_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            targets_path = Path(tmp) / "targets.json"

            saved = worker.save_app_config(
                str(config_path),
                {
                    "source_languages": [
                        {"code": "en", "language": "English", "enabled": True},
                        {"code": "ja", "language": "Japanese", "enabled": False},
                    ],
                    "target_languages": [
                        {"code": "zh", "language": "Simplified Chinese", "enabled": True},
                        {"code": "ja", "language": "Japanese", "enabled": False},
                    ],
                    "media_roots": [str(Path(tmp) / "media")],
                    "bazarr_url": "http://bazarr.local:6767",
                    "bazarr_api_key": "secret",
                    "gemini_api_key": "gemini-1",
                    "gemini_api_key2": "gemini-2",
                    "tmdb_api_key": "tmdb",
                },
                postprocess_targets_path=str(targets_path),
            )

            self.assertEqual(saved["source_languages"][0]["code"], "en")
            self.assertEqual(saved["target_languages"][0]["code"], "zh")
            self.assertEqual(saved["bazarr_url"], "http://bazarr.local:6767")
            self.assertEqual(saved["bazarr_api_key"], "secret")
            self.assertEqual(saved["gemini_api_key"], "gemini-1")
            self.assertEqual(saved["gemini_api_key2"], "gemini-2")
            self.assertEqual(saved["tmdb_api_key"], "tmdb")
            self.assertTrue(config_path.exists())
            self.assertEqual(
                json.loads(targets_path.read_text(encoding="utf-8")),
                {
                    "source_languages": [{"code": "en", "language": "English", "enabled": True}],
                    "target_languages": [{"code": "zh", "language": "Simplified Chinese", "enabled": True}],
                },
            )

    def test_save_app_config_persists_gst_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"

            saved = worker.save_app_config(
                str(config_path),
                {
                    "gst_model": "gemini-2.5-flash",
                    "gst_batch_size": 500,
                    "gst_paid_quota": True,
                    "gst_skip_upgrade": False,
                    "gst_quiet": False,
                    "gst_progress_log": True,
                    "gst_thoughts_log": True,
                    "gst_temperature": "0.7",
                    "gst_top_p": "0.95",
                    "gst_top_k": "40",
                    "gst_thinking_budget": "2048",
                    "gst_thinking_level": "medium",
                    "gst_no_streaming": True,
                    "gst_no_thinking": True,
                    "gst_token_report": True,
                    "gst_token_stats": True,
                    "gst_no_context": True,
                    "job_settle_seconds": 600,
                },
            )

            self.assertEqual(saved["gst_model"], "gemini-2.5-flash")
            self.assertEqual(saved["gst_batch_size"], 500)
            self.assertTrue(saved["gst_paid_quota"])
            self.assertFalse(saved["gst_skip_upgrade"])
            self.assertFalse(saved["gst_quiet"])
            self.assertTrue(saved["gst_progress_log"])
            self.assertTrue(saved["gst_thoughts_log"])
            self.assertEqual(saved["gst_temperature"], "0.7")
            self.assertEqual(saved["gst_top_p"], "0.95")
            self.assertEqual(saved["gst_top_k"], "40")
            self.assertEqual(saved["gst_thinking_budget"], "2048")
            self.assertEqual(saved["gst_thinking_level"], "medium")
            self.assertTrue(saved["gst_no_streaming"])
            self.assertTrue(saved["gst_no_thinking"])
            self.assertTrue(saved["gst_token_report"])
            self.assertNotIn("gst_token_stats", saved)
            self.assertTrue(saved["gst_no_context"])
            self.assertEqual(saved["job_settle_seconds"], 600)

    def test_default_gst_tuning_matches_recommended_automation_profile(self):
        config = worker.normalize_app_config({})

        self.assertEqual(config["gst_batch_size"], 1000)
        self.assertEqual(config["job_settle_seconds"], 600)
        self.assertEqual(config["gst_temperature"], "0.7")
        self.assertEqual(config["gst_top_p"], "0.95")
        self.assertEqual(config["gst_top_k"], "40")
        self.assertEqual(config["gst_thinking_budget"], "2048")
        self.assertEqual(config["gst_thinking_level"], "medium")
        self.assertTrue(config["gst_no_streaming"])
        self.assertFalse(config["gst_paid_quota"])

    def test_save_app_config_preserves_blank_secret_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            worker.save_app_config(
                str(config_path),
                {
                    "bazarr_api_key": "bazarr-secret",
                    "gemini_api_key": "gemini-secret",
                    "gemini_api_key2": "gemini-secret-2",
                    "tmdb_api_key": "tmdb-secret",
                },
            )

            saved = worker.save_app_config(
                str(config_path),
                {
                    "bazarr_url": "http://new-bazarr:6767",
                    "bazarr_api_key": "",
                    "gemini_api_key": "",
                    "gemini_api_key2": "",
                    "tmdb_api_key": "",
                },
            )

            self.assertEqual(saved["bazarr_api_key"], "bazarr-secret")
            self.assertEqual(saved["gemini_api_key"], "gemini-secret")
            self.assertEqual(saved["gemini_api_key2"], "gemini-secret-2")
            self.assertEqual(saved["tmdb_api_key"], "tmdb-secret")

    def test_save_app_config_preserves_masked_secret_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            worker.save_app_config(
                str(config_path),
                {
                    "bazarr_api_key": "bazarr-secret",
                    "gemini_api_key": "gemini-secret",
                    "gemini_api_key2": "gemini-secret-2",
                    "tmdb_api_key": "tmdb-secret",
                },
            )

            saved = worker.save_app_config(
                str(config_path),
                {
                    "bazarr_api_key": "**********",
                    "gemini_api_key": "**********",
                    "gemini_api_key2": "**********",
                    "tmdb_api_key": "**********",
                },
            )

            self.assertEqual(saved["bazarr_api_key"], "bazarr-secret")
            self.assertEqual(saved["gemini_api_key"], "gemini-secret")
            self.assertEqual(saved["gemini_api_key2"], "gemini-secret-2")
            self.assertEqual(saved["tmdb_api_key"], "tmdb-secret")

    def test_public_app_config_hides_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            worker.save_app_config(
                str(config_path),
                {
                    "bazarr_url": "http://bazarr:6767",
                    "bazarr_api_key": "bazarr-secret",
                    "gemini_api_key": "gemini-secret",
                    "gemini_api_key2": "gemini-secret-2",
                    "tmdb_api_key": "tmdb-secret",
                },
            )

            public = worker.public_app_config(str(config_path))

            self.assertEqual(public["bazarr_api_key"], "**********")
            self.assertEqual(public["gemini_api_key"], "**********")
            self.assertEqual(public["gemini_api_key2"], "**********")
            self.assertEqual(public["tmdb_api_key"], "**********")
            self.assertTrue(public["bazarr_api_key_configured"])
            self.assertTrue(public["gemini_api_key_configured"])
            self.assertTrue(public["gemini_api_key2_configured"])
            self.assertTrue(public["tmdb_api_key_configured"])

    def test_load_settings_reads_app_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            worker.save_app_config(
                str(config_path),
                {
                    "bazarr_url": "http://bazarr.local:6767",
                    "bazarr_api_key": "bazarr-secret",
                    "gemini_api_key": "gemini-secret",
                    "gemini_api_key2": "gemini-secret-2",
                    "tmdb_api_key": "tmdb-secret",
                },
            )

            settings = worker.load_settings(str(config_path))

            self.assertEqual(settings["bazarr_url"], "http://bazarr.local:6767")
            self.assertEqual(settings["bazarr_api_key"], "bazarr-secret")
            self.assertEqual(settings["gemini_api_key"], "gemini-secret")
            self.assertEqual(settings["gemini_api_key2"], "gemini-secret-2")
            self.assertEqual(settings["tmdb_api_key"], "tmdb-secret")

    def test_translation_environment_uses_configured_gemini_keys(self):
        env = worker.translation_environment(
            {
                "gemini_api_key": "gemini-secret",
                "gemini_api_key2": "gemini-secret-2",
            },
            base_env={},
        )

        self.assertEqual(env["GEMINI_API_KEY"], "gemini-secret")
        self.assertEqual(env["GEMINI_API_KEY1"], "gemini-secret")
        self.assertEqual(env["GEMINI_API_KEY2"], "gemini-secret-2")

    def test_seed_app_config_from_settings_writes_missing_runtime_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            targets_path = Path(tmp) / "targets.json"
            worker.save_app_config(str(config_path), {"bazarr_url": "http://old:6767"})

            seeded = worker.seed_app_config_from_settings(
                str(config_path),
                {
                    "bazarr_url": "http://old:6767",
                    "bazarr_api_key": "bazarr-secret",
                    "gemini_api_key": "gemini-secret",
                    "gemini_api_key2": "gemini-secret-2",
                    "tmdb_api_key": "tmdb-secret",
                },
                str(targets_path),
            )

            self.assertTrue(seeded)
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["bazarr_api_key"], "bazarr-secret")
            self.assertEqual(saved["gemini_api_key"], "gemini-secret")
            self.assertEqual(saved["gemini_api_key2"], "gemini-secret-2")
            self.assertEqual(saved["tmdb_api_key"], "tmdb-secret")

    def test_create_backup_writes_config_and_targets_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "state" / "config.json"
            targets_path = root / "postprocess" / "targets.json"
            config_path.parent.mkdir()
            targets_path.parent.mkdir()
            config_path.write_text('{"gemini_api_key":"secret"}', encoding="utf-8")
            targets_path.write_text('{"target_languages":[]}', encoding="utf-8")

            backup = worker.create_backup(str(root / "state"), str(config_path), str(targets_path), reason="manual")

            self.assertTrue(Path(backup["path"]).exists())
            self.assertEqual(backup["name"], Path(backup["path"]).name)
            self.assertTrue(backup["name"].startswith("gemini-srt-translator-bazarr-manual-"))
            with zipfile.ZipFile(backup["path"]) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    ["backup.json", "config/config.json", "postprocess/targets.json"],
                )
                metadata = json.loads(archive.read("backup.json").decode("utf-8"))
            self.assertEqual(metadata["app"], "gemini-srt-translator-bazarr")
            self.assertEqual(metadata["reason"], "manual")

    def test_backup_file_path_accepts_only_existing_backup_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp) / "backups"
            backup_dir.mkdir()
            backup_path = backup_dir / "safe.zip"
            backup_path.write_bytes(b"zip")

            self.assertEqual(worker.backup_file_path(tmp, "safe.zip"), backup_path)

            for name in ("", "../safe.zip", "..\\safe.zip", "/tmp/safe.zip", "missing.zip"):
                with self.assertRaises(ValueError):
                    worker.backup_file_path(tmp, name)

    def test_restore_backup_archive_writes_config_and_targets_after_pre_import_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "state" / "config.json"
            targets_path = root / "postprocess" / "targets.json"
            config_path.parent.mkdir()
            targets_path.parent.mkdir()
            config_path.write_text('{"gemini_api_key":"old"}', encoding="utf-8")
            targets_path.write_text('{"target_languages":[{"code":"zh"}]}', encoding="utf-8")

            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w") as archive:
                archive.writestr("backup.json", '{"app":"gemini-srt-translator-bazarr"}')
                archive.writestr("config/config.json", '{"gemini_api_key":"new"}')
                archive.writestr("postprocess/targets.json", '{"target_languages":[{"code":"en"}]}')

            result = worker.restore_backup_archive(
                payload.getvalue(),
                str(root / "state"),
                str(config_path),
                str(targets_path),
                now=2_000_000,
            )

            self.assertEqual(result["imported"], ["config/config.json", "postprocess/targets.json"])
            self.assertTrue(result["pre_import_backup"]["name"].startswith("gemini-srt-translator-bazarr-pre-import-"))
            self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["gemini_api_key"], "new")
            self.assertEqual(json.loads(targets_path.read_text(encoding="utf-8"))["target_languages"][0]["code"], "en")

    def test_restore_backup_archive_rejects_invalid_zip_without_pre_import_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "state" / "config.json"
            targets_path = root / "postprocess" / "targets.json"
            config_path.parent.mkdir()
            targets_path.parent.mkdir()
            config_path.write_text('{"gemini_api_key":"old"}', encoding="utf-8")
            targets_path.write_text('{"target_languages":[]}', encoding="utf-8")

            with self.assertRaises(ValueError):
                worker.restore_backup_archive(
                    b"not a zip",
                    str(root / "state"),
                    str(config_path),
                    str(targets_path),
                )

            self.assertFalse((root / "state" / "backups").exists())
            self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["gemini_api_key"], "old")

    def test_list_backups_returns_zip_files_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp) / "backups"
            backup_dir.mkdir()
            older = backup_dir / "older.zip"
            newer = backup_dir / "newer.zip"
            older.write_text("old", encoding="utf-8")
            newer.write_text("new", encoding="utf-8")
            now = time.time()
            os.utime(older, (now - 20, now - 20))
            os.utime(newer, (now - 10, now - 10))

            backups = worker.list_backups(tmp)

            self.assertEqual([item["name"] for item in backups], ["newer.zip", "older.zip"])

    def test_purge_old_backups_deletes_files_older_than_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp) / "backups"
            backup_dir.mkdir()
            now = 2_000_000
            old = backup_dir / "old.zip"
            recent = backup_dir / "recent.zip"
            old.write_text("old", encoding="utf-8")
            recent.write_text("recent", encoding="utf-8")
            os.utime(old, (now - 31 * 86400, now - 31 * 86400))
            os.utime(recent, (now - 29 * 86400, now - 29 * 86400))

            deleted = worker.purge_old_backups(tmp, now=now, retention_days=30)

            self.assertEqual(deleted, [str(old)])
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())

    def test_create_scheduled_backup_if_due_runs_every_seven_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "state" / "config.json"
            targets_path = root / "postprocess" / "targets.json"
            config_path.parent.mkdir()
            targets_path.parent.mkdir()
            config_path.write_text('{"gemini_api_key":"secret"}', encoding="utf-8")
            targets_path.write_text('{"target_languages":[]}', encoding="utf-8")
            now = 2_000_000

            first = worker.create_scheduled_backup_if_due(str(root / "state"), str(config_path), str(targets_path), now=now)
            second = worker.create_scheduled_backup_if_due(str(root / "state"), str(config_path), str(targets_path), now=now + 6 * 86400)
            third = worker.create_scheduled_backup_if_due(str(root / "state"), str(config_path), str(targets_path), now=now + 8 * 86400)

            self.assertIsNotNone(first)
            self.assertIsNone(second)
            self.assertIsNotNone(third)
            self.assertIn("scheduled", first["name"])
            self.assertIn("scheduled", third["name"])

    def test_manual_backup_does_not_suppress_scheduled_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "state" / "config.json"
            targets_path = root / "postprocess" / "targets.json"
            config_path.parent.mkdir()
            targets_path.parent.mkdir()
            config_path.write_text('{"gemini_api_key":"secret"}', encoding="utf-8")
            targets_path.write_text('{"target_languages":[]}', encoding="utf-8")
            now = 2_000_000

            worker.create_backup(str(root / "state"), str(config_path), str(targets_path), reason="manual", now=now)
            scheduled = worker.create_scheduled_backup_if_due(str(root / "state"), str(config_path), str(targets_path), now=now + 60)

            self.assertIsNotNone(scheduled)
            self.assertIn("scheduled", scheduled["name"])

    def test_settings_from_payload_uses_mask_as_existing_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            worker.save_app_config(
                str(config_path),
                {
                    "bazarr_url": "http://old:6767",
                    "bazarr_api_key": "bazarr-secret",
                    "gemini_api_key": "gemini-secret",
                    "gemini_api_key2": "gemini-secret-2",
                    "tmdb_api_key": "tmdb-secret",
                },
            )

            settings = worker.settings_from_payload(
                str(config_path),
                {
                    "bazarr_url": "http://new:6767",
                    "bazarr_api_key": "**********",
                    "gemini_api_key": "new-gemini",
                    "gemini_api_key2": "**********",
                    "tmdb_api_key": "",
                },
            )

            self.assertEqual(settings["bazarr_url"], "http://new:6767")
            self.assertEqual(settings["bazarr_api_key"], "bazarr-secret")
            self.assertEqual(settings["gemini_api_key"], "new-gemini")
            self.assertEqual(settings["gemini_api_key2"], "gemini-secret-2")
            self.assertEqual(settings["tmdb_api_key"], "tmdb-secret")

    def test_connection_tests_call_expected_api(self):
        http = FakeHTTP(
            {
                ("http://bazarr:6767/api/system/languages", ()): [],
                ("https://generativelanguage.googleapis.com/v1beta/models", (("key", "gemini-secret"),)): {"models": []},
                ("https://api.themoviedb.org/3/configuration", (("api_key", "tmdb-secret"),)): {"images": {}},
            }
        )
        settings = {
            "bazarr_url": "http://bazarr:6767",
            "bazarr_api_key": "bazarr-secret",
            "gemini_api_key": "gemini-secret",
            "gemini_api_key2": "gemini-secret",
            "tmdb_api_key": "tmdb-secret",
        }

        self.assertTrue(worker.test_connection("bazarr", settings, http)["ok"])
        self.assertTrue(worker.test_connection("gemini_api_key", settings, http)["ok"])
        self.assertTrue(worker.test_connection("tmdb_api_key", settings, http)["ok"])
        self.assertEqual(
            http.calls,
            [
                ("GET", "http://bazarr:6767/api/system/languages", {}, {"X-API-KEY": "bazarr-secret"}),
                ("GET", "https://generativelanguage.googleapis.com/v1beta/models", {"key": "gemini-secret"}, {}),
                ("GET", "https://api.themoviedb.org/3/configuration", {"api_key": "tmdb-secret"}, {}),
            ],
        )

    def test_gemini_models_returns_api_models_with_fallback(self):
        http = FakeHTTP(
            {
                (
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    (("key", "gemini-secret"),),
                ): {
                    "models": [
                        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                        {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
                    ]
                }
            }
        )

        models = worker.gemini_models(http, {"gemini_api_key": "gemini-secret"})

        self.assertEqual(models[0], {"id": "gemini-2.5-flash", "name": "gemini-2.5-flash"})
        self.assertNotIn("embedding-001", [item["id"] for item in models])
        self.assertIn(("GET", "https://generativelanguage.googleapis.com/v1beta/models", {"key": "gemini-secret"}, {}), http.calls)

    def test_clear_logs_truncates_worker_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "worker.log"
            log_path.write_text("line one\nline two\n", encoding="utf-8")

            result = worker.clear_logs(tmp)

            self.assertTrue(result)
            self.assertEqual(log_path.read_text(encoding="utf-8"), "")

    def test_job_should_skip_non_embedded_same_language_and_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            subtitle = Path(tmp) / "Episode.ja.srt"
            subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
            output = Path(tmp) / "Episode.zh.srt"
            output.write_text("translated", encoding="utf-8")

            self.assertTrue(worker.should_skip_job({"provider": "opensubtitles", "language": "ja", "subtitle_path": str(subtitle)}))
            self.assertTrue(
                worker.should_skip_job(
                    {"provider": "embeddedsubtitles", "source_code": "ja", "target_code": "ja", "subtitle_path": str(subtitle)}
                )
            )
            self.assertTrue(worker.should_skip_job({"provider": "embeddedsubtitles", "language": "ja", "subtitle_path": str(subtitle), "target_code": "zh"}))
            output.unlink()
            self.assertFalse(worker.should_skip_job({"provider": "embeddedsubtitles", "language": "ja", "subtitle_path": str(subtitle), "target_code": "zh"}))

    def test_job_should_skip_when_configured_target_output_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            subtitle = Path(tmp) / "Episode.en.srt"
            subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
            output = Path(tmp) / "Episode.zt.srt"
            output.write_text("translated", encoding="utf-8")

            self.assertTrue(
                worker.should_skip_job(
                    {
                        "provider": "embeddedsubtitles",
                        "source_code": "en",
                        "subtitle_path": str(subtitle),
                        "target_code": "zt",
                        "target_language": "Traditional Chinese",
                    }
                )
            )

            output.unlink()
            self.assertFalse(
                worker.should_skip_job(
                    {
                        "provider": "embeddedsubtitles",
                        "source_code": "en",
                        "subtitle_path": str(subtitle),
                        "target_code": "zt",
                        "target_language": "Traditional Chinese",
                    }
                )
            )

    def test_enqueue_translation_jobs_for_enabled_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_dir = Path(tmp) / "queue"
            subtitle = Path(tmp) / "Movie.ja.srt"
            subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
            (Path(tmp) / "Movie.zh.srt").write_text("existing", encoding="utf-8")

            created = worker.enqueue_translation_jobs(
                queue_dir=str(queue_dir),
                base_job={
                    "video_path": str(Path(tmp) / "Movie.mkv"),
                    "subtitle_path": str(subtitle),
                    "provider": "embeddedsubtitles",
                    "source_code": "ja",
                    "source_language": "Japanese",
                    "media_id": "781",
                    "media_type": "movie",
                },
                targets=[
                    {"code": "zh", "language": "Simplified Chinese", "enabled": True},
                    {"code": "zt", "language": "Traditional Chinese", "enabled": True},
                ],
            )

            self.assertEqual(len(created), 1)
            job = json.loads(Path(created[0]).read_text(encoding="utf-8"))
            self.assertEqual(job["target_code"], "zt")
            self.assertEqual(job["target_language"], "Traditional Chinese")
            self.assertEqual(job["output_path"], str(Path(tmp) / "Movie.zt.srt"))
            self.assertEqual(job["source_code"], "ja")
            self.assertEqual(job["source_language"], "Japanese")

    def test_enqueue_translation_jobs_skips_same_source_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_dir = Path(tmp) / "queue"
            subtitle = Path(tmp) / "Movie.zh.srt"
            subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")

            created = worker.enqueue_translation_jobs(
                queue_dir=str(queue_dir),
                base_job={
                    "video_path": str(Path(tmp) / "Movie.mkv"),
                    "subtitle_path": str(subtitle),
                    "provider": "embeddedsubtitles",
                    "source_code": "zh",
                    "source_language": "Simplified Chinese",
                    "media_id": "781",
                    "media_type": "movie",
                },
                targets=[
                    {"code": "zh", "language": "Simplified Chinese", "enabled": True},
                    {"code": "en", "language": "English", "enabled": True},
                ],
            )

            self.assertEqual(len(created), 1)
            job = json.loads(Path(created[0]).read_text(encoding="utf-8"))
            self.assertEqual(job["target_code"], "en")
            self.assertEqual(job["output_path"], str(Path(tmp) / "Movie.en.srt"))

    def test_queue_snapshot_counts_job_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_dir = Path(tmp)
            for state in ("pending", "processing", "done", "failed"):
                (queue_dir / state).mkdir()
            (queue_dir / "pending" / "a.json").write_text('{"job_id":"a"}', encoding="utf-8")
            (queue_dir / "failed" / "b.json").write_text('{"job_id":"b"}', encoding="utf-8")
            (queue_dir / "failed" / "b.error").write_text("boom", encoding="utf-8")

            snapshot = worker.queue_snapshot(str(queue_dir))

            self.assertEqual(snapshot["counts"]["pending"], 1)
            self.assertEqual(snapshot["counts"]["failed"], 1)
            self.assertEqual(snapshot["failed"][0]["error"], "boom")

    def test_queue_worker_waits_for_settle_window_before_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue_dir = root / "queue"
            for state in ("pending", "processing", "done", "failed"):
                (queue_dir / state).mkdir(parents=True)
            subtitle = root / "Movie.en.srt"
            output = root / "Movie.zh.srt"
            subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
            job = {
                "job_id": "settle-race",
                "created_at": 1_000,
                "subtitle_path": str(subtitle),
                "output_path": str(output),
                "source_code": "en",
                "target_code": "zh",
                "provider": "embeddedsubtitles",
            }
            (queue_dir / "pending" / "settle-race.json").write_text(json.dumps(job), encoding="utf-8")
            queue_worker = worker.QueueWorker(
                str(queue_dir),
                {"bazarr_url": "http://bazarr:6767", "bazarr_api_key": "", "tmdb_api_key": "", "job_settle_seconds": 120},
                worker.MemoryCache(),
                FakeHTTP({}),
            )

            self.assertFalse(queue_worker.process_once(now=1_060))
            self.assertTrue((queue_dir / "pending" / "settle-race.json").exists())

            output.write_text("embedded zh subtitle", encoding="utf-8")
            self.assertTrue(queue_worker.process_once(now=1_121))
            self.assertTrue((queue_dir / "done" / "settle-race.json").exists())
            self.assertEqual(output.read_text(encoding="utf-8"), "embedded zh subtitle")

    def test_run_translation_does_not_overwrite_output_created_during_gst(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subtitle = root / "Movie.en.srt"
            output = root / "Movie.zh.srt"
            subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")

            def fake_run(command, **kwargs):
                temp_output = Path(command[command.index("-o") + 1])
                temp_output.write_text("gemini translation", encoding="utf-8")
                output.write_text("embedded zh subtitle", encoding="utf-8")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch("gst_worker.translation.subprocess.run", side_effect=fake_run):
                status = worker.run_translation(
                    {
                        "subtitle_path": str(subtitle),
                        "output_path": str(output),
                        "target_code": "zh",
                        "target_language": "Simplified Chinese",
                    },
                    "",
                    {"gemini_api_key": "secret"},
                )

            self.assertEqual(status, "skipped-existing-output")
            self.assertEqual(output.read_text(encoding="utf-8"), "embedded zh subtitle")
            self.assertFalse((root / "Movie.zh.partial.srt").exists())

    def test_scan_source_subtitles_finds_missing_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Show").mkdir()
            (root / "Show" / "Episode.ja.srt").write_text("hello", encoding="utf-8")
            (root / "Show" / "Episode.zh.srt").write_text("existing", encoding="utf-8")

            items = worker.scan_source_subtitles(
                roots=[str(root)],
                source_languages=[
                    {"code": "en", "language": "English", "enabled": True},
                    {"code": "ja", "language": "Japanese", "enabled": True},
                ],
                target_languages=[
                    {"code": "zh", "language": "Simplified Chinese", "enabled": True},
                    {"code": "zt", "language": "Traditional Chinese", "enabled": True},
                ],
                limit=10,
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["subtitle_path"], str(root / "Show" / "Episode.ja.srt"))
            self.assertEqual(items[0]["source_code"], "ja")
            self.assertEqual(items[0]["source_language"], "Japanese")
            self.assertEqual(items[0]["missing_targets"], [{"code": "zt", "language": "Traditional Chinese", "enabled": True}])

    def test_movie_description_prefers_tmdb_id_from_path(self):
        http = FakeHTTP({
            (
                "https://api.themoviedb.org/3/movie/350",
                (("api_key", "tmdb-key"), ("language", "en-US")),
            ): {
                "title": "The Devil Wears Prada",
                "release_date": "2006-06-30",
                "overview": "A smart graduate works for a fashion editor.",
                "genres": [{"name": "Comedy"}, {"name": "Drama"}],
            }
        })
        job = {
            "media_type": "movie",
            "video_path": "/media/Movie/The Devil Wears Prada (2006)/The Devil Wears Prada (2006) {tmdb-350}.mkv",
            "media_id": "781",
        }

        description = worker.build_tmdb_description(
            job,
            bazarr=FakeHTTP(),
            tmdb=http,
            bazarr_url="http://bazarr:6767",
            bazarr_api_key="bazarr-key",
            tmdb_api_key="tmdb-key",
            cache=worker.MemoryCache(),
        )

        self.assertIn("Overview: A smart graduate works for a fashion editor.", description)
        self.assertIn("The Devil Wears Prada - 2006", description)
        self.assertIn("Genre(s): Comedy, Drama", description)

    def test_series_description_uses_bazarr_tvdb_mapping_and_episode(self):
        bazarr = FakeHTTP({
            (
                "http://bazarr:6767/api/series",
                (("seriesid[]", "257"),),
            ): {"data": [{"title": "NCIS: Sydney", "tvdbId": 416493, "imdbId": "tt18258908", "overview": "Bazarr overview"}]},
            (
                "http://bazarr:6767/api/episodes",
                (("episodeid[]", "14569"),),
            ): {"data": [{"season": 3, "episode": 16, "title": "Ticker"}]},
        })
        tmdb = FakeHTTP({
            (
                "https://api.themoviedb.org/3/find/416493",
                (("api_key", "tmdb-key"), ("external_source", "tvdb_id")),
            ): {"tv_results": [{"id": 222766}]},
            (
                "https://api.themoviedb.org/3/tv/222766",
                (("api_key", "tmdb-key"), ("language", "en-US")),
            ): {"name": "NCIS: Sydney", "overview": "Show overview"},
            (
                "https://api.themoviedb.org/3/tv/222766/season/3/episode/16",
                (("api_key", "tmdb-key"), ("language", "en-US")),
            ): {"name": "Ticker", "overview": "Episode overview"},
        })
        job = {"media_type": "series", "series_id": "257", "media_id": "14569"}

        description = worker.build_tmdb_description(
            job,
            bazarr=bazarr,
            tmdb=tmdb,
            bazarr_url="http://bazarr:6767",
            bazarr_api_key="bazarr-key",
            tmdb_api_key="tmdb-key",
            cache=worker.MemoryCache(),
        )

        self.assertIn("Episode Overview: Episode overview", description)
        self.assertIn("NCIS: Sydney S03E16 - Ticker", description)
        self.assertIn("Show Overview: Show overview", description)

    def test_refresh_bazarr_uses_series_or_movie_scan_disk(self):
        http = FakeHTTP()
        worker.refresh_bazarr(
            {"media_type": "series", "series_id": "257", "media_id": "14569"},
            http=http,
            bazarr_url="http://bazarr:6767",
            api_key="bazarr-key",
        )
        worker.refresh_bazarr(
            {"media_type": "movie", "media_id": "781"},
            http=http,
            bazarr_url="http://bazarr:6767",
            api_key="bazarr-key",
        )

        self.assertEqual(
            http.calls,
            [
                ("PATCH", "http://bazarr:6767/api/series", {"seriesid": "257", "action": "scan-disk"}, {"X-API-KEY": "bazarr-key"}),
                ("PATCH", "http://bazarr:6767/api/movies", {"radarrid": "781", "action": "scan-disk"}, {"X-API-KEY": "bazarr-key"}),
            ],
        )

    def test_build_gst_command_uses_job_target_language(self):
        command = worker.build_gst_command(
            "/media/Movie.en.srt",
            "/media/Movie.zt.srt",
            "",
            target_language="Traditional Chinese",
        )

        self.assertEqual(command[command.index("-l") + 1], "Traditional Chinese")

    def test_build_gst_command_uses_configured_gst_settings(self):
        command = worker.build_gst_command(
            "/media/Movie.en.srt",
            "/media/Movie.zh.srt",
            "",
            target_language="Simplified Chinese",
            gst_settings={
                "gst_model": "gemini-2.5-flash",
                "gst_batch_size": 500,
                "gst_paid_quota": True,
                "gst_skip_upgrade": False,
                "gst_quiet": False,
                "gst_progress_log": True,
                "gst_thoughts_log": True,
                "gst_temperature": "0.7",
                "gst_top_p": "0.95",
                "gst_top_k": "40",
                "gst_thinking_budget": "2048",
                "gst_thinking_level": "medium",
                "gst_no_streaming": True,
                "gst_no_thinking": True,
                "gst_token_report": True,
                "gst_token_stats": True,
                "gst_no_context": True,
            },
        )

        self.assertEqual(command[command.index("--model") + 1], "gemini-2.5-flash")
        self.assertEqual(command[command.index("--batch-size") + 1], "500")
        self.assertIn("--paid-quota", command)
        self.assertIn("--progress-log", command)
        self.assertIn("--thoughts-log", command)
        self.assertIn("--no-streaming", command)
        self.assertIn("--no-thinking", command)
        self.assertIn("--token-report", command)
        self.assertNotIn("--token-stats", command)
        self.assertIn("--no-context", command)
        self.assertIn("--temperature", command)
        self.assertIn("--top-p", command)
        self.assertIn("--top-k", command)
        self.assertIn("--thinking-budget", command)
        self.assertIn("--thinking-level", command)
        self.assertNotIn("--skip-upgrade", command)
        self.assertNotIn("--quiet", command)


if __name__ == "__main__":
    unittest.main()
