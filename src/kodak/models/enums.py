"""Shared enums for the domain model."""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    admin = "admin"
    employee = "employee"


class ProductCategory(str, Enum):
    photo = "photo"              # ფოტო სურათი
    enlargement = "enlargement"  # გადიდება
    frame = "frame"              # ჩარჩო
    lamination = "lamination"    # ლამინირება
    cd = "cd"
    photocopy = "photocopy"      # ქსეროქსი
    album = "album"
    other = "other"


class CreditStatus(str, Enum):
    active   = "active"    # nothing paid back yet
    partial  = "partial"   # some paid, balance remaining
    cleared  = "cleared"   # fully paid back
    forgiven = "forgiven"  # admin pardoned the remaining balance


class StockCategory(str, Enum):
    frame = "frame"
    photo_paper = "photo_paper"
    lamination_sheet = "lamination_sheet"
    cd = "cd"
    letter_paper = "letter_paper"
    color_cartridge = "color_cartridge"
    xerox_cartridge = "xerox_cartridge"
    sticker = "sticker"
    embossed_paper = "embossed_paper"
