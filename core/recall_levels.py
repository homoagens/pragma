# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""How much a recall is offered and how much it may take: few, medium, many.

The numbers behind each word, and nothing else. config reads them to set the
curator up, and the launcher's /settings page reads them to say what each
word means. They used to be written twice, the page's copy by hand because
importing config asks the model server for its window; this module asks
nothing, so both read the one table. What the levels do is explained in
config, where they are applied.
"""

LEVELS = ("few", "medium", "many")

# How many of each are put in front of the curator.
OFFERED = {
    "episodes":  {"few": 5, "medium": 10, "many": 20},
    "recent":    {"few": 2, "medium": 3,  "many": 5},     # of those, the latest
    "learnings": {"few": 4, "medium": 8,  "many": 16},
}

# The most it may take, of each kind.
TAKEN = {"few": 3, "medium": 5, "many": 8}
