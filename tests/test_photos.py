from unittest.mock import patch

from tests.support import ArchiveTestCase


class PhotosTests(ArchiveTestCase):
    def setUp(self):
        super().setUp()
        for name, value in (
            ("photos_ok", (True, "Mock Photos")),
            ("ensure_album", "test-album"),
            ("find_photo", ""),
            ("import_photo", "test-import"),
            ("set_meta", "test-update"),
            ("managed_ids", ["managed-1", "managed-2"]),
            ("del_photos", None),
        ):
            patcher = patch.object(self.archive, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def photo_record(self, name="label.jpg", **attachment_fields):
        return self.create_record(
            attachments=[
                {
                    "path": str(self.source(name, name.encode())),
                    **attachment_fields,
                }
            ]
        )

    def test_sync_dry_run_has_no_mutations(self):
        self.photo_record()
        result = self.archive.psync(True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["actions"][0]["action"], "import")
        self.ensure_album.assert_not_called()
        self.import_photo.assert_not_called()
        self.set_meta.assert_not_called()
        self.del_photos.assert_not_called()

    def test_sync_updates_existing_and_imports_missing(self):
        self.photo_record("first.jpg")
        self.photo_record("second.jpg")
        self.find_photo.side_effect = ["existing-photo", ""]
        result = self.archive.psync(False)
        self.assertEqual([a["action"] for a in result["actions"]], ["update", "import"])
        self.assertEqual(self.set_meta.call_args.args[0], "existing-photo")
        self.import_photo.assert_called_once()
        self.del_photos.assert_not_called()

    def test_projection_excludes_removed_deleted_and_opted_out(self):
        removed = self.photo_record("removed.jpg")
        self.archive.rmatt(removed["attachments"][0]["id"])
        deleted = self.photo_record("deleted.jpg")
        self.archive.delete(deleted["id"])
        self.photo_record("private.jpg", publish_to_photos=False)
        active = self.photo_record("active.jpg")
        self.assertEqual(
            [a["id"] for _, a, _ in self.archive.photo_items()],
            [active["attachments"][0]["id"]],
        )

    def test_rebuild_preview_never_deletes_even_with_confirmation(self):
        self.photo_record()
        result = self.archive.prebuild(True, True)
        self.assertEqual(result["managed_assets_to_delete"], 2)
        self.assertEqual(result["then_reimport"], 1)
        self.del_photos.assert_not_called()
        self.import_photo.assert_not_called()

    def test_rebuild_requires_confirmation(self):
        self.assertFalse(self.archive.prebuild(False, False)["ok"])
        self.del_photos.assert_not_called()
        self.import_photo.assert_not_called()

    def test_rebuild_deletes_only_ids_from_managed_selection(self):
        with patch.object(self.archive, "psync", return_value={"ok": True}) as sync:
            result = self.archive.prebuild(False, True)
        self.assertTrue(result["ok"])
        self.del_photos.assert_called_once_with(["managed-1", "managed-2"])
        sync.assert_called_once_with(False)

    def test_unavailable_photos_does_not_prevent_archival(self):
        self.photos_ok.return_value = (False, "Mock permission denied")
        record = self.photo_record()
        before = self.snapshot()
        self.assertFalse(self.archive.psync(False)["ok"])
        self.assertFalse(self.archive.prebuild(False, True)["ok"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.archive.load(record["id"]), record)
        self.del_photos.assert_not_called()
        self.import_photo.assert_not_called()
