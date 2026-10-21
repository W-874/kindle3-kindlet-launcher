import pathlib
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import make_launcher


ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN_CLASS = 'com/mobileread/ixtab/kindlelauncher/KualKindlet.class'


class TemplateValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(ROOT / 'template/base.azw2') as archive:
            cls.original = archive.read(MAIN_CLASS)

    def patch(self, data):
        return make_launcher.patch_kindlet_class(
            data, 'printf done', '/mnt/us', 'Launcher', 'Starting', 'Returning home')

    def test_invalid_class_is_rejected(self):
        with self.assertRaises(ValueError):
            self.patch(b'\0\0\0\0' + self.original[4:])

    def test_missing_lifecycle_method_is_rejected(self):
        damaged = self.original.replace(b'longStart', b'wrongName')
        self.assertNotEqual(self.original, damaged)
        with self.assertRaises(ValueError):
            self.patch(damaged)

    def test_already_patched_template_is_rejected(self):
        with self.assertRaises(ValueError):
            self.patch(self.patch(self.original))

    def test_truncated_template_is_rejected(self):
        with self.assertRaises(ValueError):
            self.patch(self.original[:-1])

    def test_missing_entry_class_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = pathlib.Path(directory)
            template = directory / 'missing.azw2'
            output = directory / 'candidate.azw2'
            with zipfile.ZipFile(ROOT / 'template/base.azw2') as source:
                with zipfile.ZipFile(template, 'w') as target:
                    for item in source.infolist():
                        if item.filename != MAIN_CLASS:
                            target.writestr(item, source.read(item))
            with self.assertRaises(ValueError):
                make_launcher.build_launcher(
                    str(template), str(ROOT / 'keys'), str(output),
                    'Candidate', 'printf done', '/mnt/us')
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
