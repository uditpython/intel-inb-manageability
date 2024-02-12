import unittest
from unittest import mock
from xml.etree.ElementTree import Element, tostring

from dispatcher.xmlhandler import XmlHandler


class TestXmlHandler(unittest.TestCase):
    def setUp(self):
        self.xml = """
        <root>
            <element1 attribute="value1">Text1</element1>
            <element2 attribute="value2">Text2</element2>
        </root>
        """
        self.xml_handler = XmlHandler(self.xml, is_file=False, schema_location="schema.xsd")

    def test_get_element(self):
        xpath = "/root/element1"
        expected_result = "Text1"
        result = self.xml_handler.get_element(xpath)
        self.assertEqual(result, expected_result)

    def test_get_element_invalid_xpath(self):
        xpath = "/root/element3"
        with self.assertRaises(Exception):
            self.xml_handler.get_element(xpath)

    def test_get_children(self):
        xpath = "/root"
        expected_result = {
            "element1": "Text1",
            "element2": "Text2"
        }
        result = self.xml_handler.get_children(xpath)
        self.assertEqual(result, expected_result)

    def test_get_children_invalid_xpath(self):
        xpath = "/root/element3"
        with self.assertRaises(Exception):
            self.xml_handler.get_children(xpath)

    def test_find_element(self):
        xpath = "/root/element1"
        expected_result = "Text1"
        result = self.xml_handler.find_element(xpath)
        self.assertEqual(result, expected_result)

    def test_find_element_invalid_xpath(self):
        xpath = "/root/element3"
        result = self.xml_handler.find_element(xpath)
        self.assertIsNone(result)

    def test_get_attribute(self):
        xpath = "/root/element1"
        attribute_name = "attribute"
        expected_result = "value1"
        result = self.xml_handler.get_attribute(xpath, attribute_name)
        self.assertEqual(result, expected_result)

    def test_get_attribute_invalid_xpath(self):
        xpath = "/root/element3"
        attribute_name = "attribute"
        with self.assertRaises(Exception):
            self.xml_handler.get_attribute(xpath, attribute_name)

    def test_add_attribute(self):
        xpath = "/root"
        attribute_name = "new_attribute"
        attribute_value = "new_value"
        expected_result = f'<root><element1 attribute="value1">Text1</element1><element2 attribute="value2">Text2</element2><new_attribute>new_value</new_attribute></root>'
        result = self.xml_handler.add_attribute(xpath, attribute_name, attribute_value)
        self.assertEqual(result, expected_result)

    def test_set_attribute(self):
        xpath = "/root/element1"
        attribute_value = "new_value"
        expected_result = f'<root><element1 attribute="value1">new_value</element1><element2 attribute="value2">Text2</element2></root>'
        result = self.xml_handler.set_attribute(xpath, attribute_value)
        self.assertEqual(result, expected_result)

    def test_remove_attribute(self):
        xpath = "/root/element1"
        expected_result = f'<root><element2 attribute="value2">Text2</element2></root>'
        result = self.xml_handler.remove_attribute(xpath)
        self.assertEqual(result, expected_result)

    def test_get_root_elements(self):
        key = "element1"
        attr = "attribute"
        expected_result = ["value1"]
        result = self.xml_handler.get_root_elements(key, attr)
        self.assertEqual(result, expected_result)

    def test_get_root_elements_invalid_key(self):
        key = "element3"
        attr = "attribute"
        with self.assertRaises(Exception):
            self.xml_handler.get_root_elements(key, attr)


if __name__ == '__main__':
    unittest.main()
