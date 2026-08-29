"""
Python 3.14 Compatibility Patch for Django Template Context Copying.
In Python 3.14, `copy(super())` in Django's BaseContext/RenderContext causes:
AttributeError: 'super' object has no attribute 'dicts' and no __dict__ for setting new attributes.
This module patches `__copy__` on BaseContext, Context, and RenderContext.
"""

import copy
import django.template.context as d_context


def _basecontext_copy(self):
    duplicate = object.__new__(self.__class__)
    duplicate.__dict__.update(self.__dict__)
    duplicate.dicts = self.dicts[:]
    return duplicate


def _context_copy(self):
    duplicate = _basecontext_copy(self)
    duplicate.render_context = copy.copy(self.render_context)
    return duplicate


def _rendercontext_copy(self):
    duplicate = object.__new__(self.__class__)
    duplicate.__dict__.update(self.__dict__)
    duplicate.dicts = self.dicts[:]
    return duplicate


# Apply monkeypatches
d_context.BaseContext.__copy__ = _basecontext_copy
d_context.Context.__copy__ = _context_copy
d_context.RenderContext.__copy__ = _rendercontext_copy
