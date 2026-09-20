from tests.support import ArchiveTestCase


class FactTests(ArchiveTestCase):
    def test_supersession_retains_provenance(self):
        record = {"facts": []}
        self.archive.add_fact(
            record,
            {
                "key": "model",
                "value": "TEST-123",
                "source": "label.txt",
                "confidence": "medium",
            },
        )
        self.archive.add_fact(
            record,
            {
                "key": "model",
                "value": "TEST-456",
                "source": "user",
            },
        )
        old, current = record["facts"]
        self.assertFalse(old["active"])
        self.assertEqual(old["value"], "TEST-123")
        self.assertEqual(old["source"], "label.txt")
        self.assertEqual(old["confidence"], "medium")
        self.assertEqual(old["superseded_by_value"], "TEST-456")
        self.assertEqual(self.archive.facts(record), {"model": current})

    def test_search_text_excludes_inactive_evidence_and_facts(self):
        record = {
            "facts": [
                {"key": "model", "value": "oldmodel", "active": False},
                {"key": "model", "value": "newmodel"},
            ],
            "attachments": [
                {"filename": "hiddenlabel", "active": False},
                {"filename": "visiblelabel"},
            ],
            "notes": [{"text": "Original user wording"}],
        }
        text = self.archive.text(record)
        self.assertNotIn("oldmodel", text)
        self.assertNotIn("hiddenlabel", text)
        self.assertIn("newmodel", text)
        self.assertIn("visiblelabel", text)
        self.assertIn("original user wording", text)

    def test_filename_component_is_bounded_and_has_no_separators(self):
        for name in ("../../receipt photo.txt", "a" * 200, "", "☃"):
            with self.subTest(name=name):
                slug = self.archive.slug(name)
                self.assertTrue(slug)
                self.assertLessEqual(len(slug), 100)
                self.assertNotIn("/", slug)
                self.assertNotIn("\\", slug)

    def test_photo_metadata_contains_durable_identifiers(self):
        record = {
            "id": "HA-20260920-0001",
            "title": "TestCo toaster",
            "keywords": ["kitchen", "kitchen"],
            "facts": [{"key": "model", "value": "TEST-123"}],
        }
        attachment = {"id": "HAA-20260920-0001", "role": "Model label"}
        title, caption, keywords = self.archive.photo_meta(record, attachment)
        self.assertEqual(title, "Model label")
        for identifier in (record["id"], attachment["id"]):
            self.assertIn(identifier, caption)
            self.assertIn(identifier, keywords)
        self.assertIn("TEST-123", caption)
        self.assertEqual(keywords.count("kitchen"), 1)
