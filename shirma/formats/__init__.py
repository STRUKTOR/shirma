"""Выбор адаптера по расширению."""
import os

from . import ooxml, text

IN_FORMATS = text.TEXT_EXT + ooxml.OOXML_EXT
OUT_FORMATS = text.TEXT_EXT_OUT + ooxml.OOXML_EXT


class Unsupported(Exception):
    pass


def ext_of(name):
    return os.path.splitext(name)[1].lower()


def learn(data, name, reg, use_ner=True):
    ext = ext_of(name)
    if ext in ooxml.OOXML_EXT:
        ooxml.learn_package(data, reg, use_ner)
    elif ext in text.TEXT_EXT_OUT:
        text.learn_file(data, ext, reg, use_ner)
    else:
        raise Unsupported(ext)


def convert(data, name, reg, direction, stats, warnings):
    ext = ext_of(name)
    if ext in ooxml.OOXML_EXT:
        return ooxml.convert_package(data, reg, direction, stats, warnings)
    if ext in text.TEXT_EXT_OUT:
        return text.convert_file(data, ext, reg, direction, stats)
    raise Unsupported(ext)


def texts(data, name):
    ext = ext_of(name)
    if ext in ooxml.OOXML_EXT:
        return ooxml.texts_of(data)
    if ext in text.TEXT_EXT_OUT:
        return text.texts_of(data)
    raise Unsupported(ext)
