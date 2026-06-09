# tests/test_import_mapper.py
import unittest
import os
import tempfile
from flask import session
from app import create_app
from app.web.import_mapper import sanitize_float, get_delimiter

class TestImportMapper(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-key'
        self.client = self.app.test_client()

    def test_sanitize_float(self):
        self.assertEqual(sanitize_float("123.45"), 123.45)
        self.assertEqual(sanitize_float("RD$ 1,234.56"), 1234.56)
        self.assertEqual(sanitize_float("1234,56"), 1234.56)
        self.assertEqual(sanitize_float(""), 0.0)
        self.assertEqual(sanitize_float(None), 0.0)
        self.assertEqual(sanitize_float("invalid"), 0.0)

    def test_get_delimiter(self):
        self.assertEqual(get_delimiter("code,name,price"), ",")
        self.assertEqual(get_delimiter("code;name;price"), ";")
        self.assertEqual(get_delimiter("code\tname\tprice"), "\t")

if __name__ == '__main__':
    unittest.main()
