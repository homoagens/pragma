# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.
#
# NOTE: keep this file pure ASCII. PowerShell 5.1 reads BOM-less files as ANSI.

@{
    RootModule        = 'Pragma.psm1'
    ModuleVersion     = '0.1.0'
    GUID              = '7f3c1a54-9d2b-4e18-b0a6-2c5e8d41f9c3'
    Author            = 'Homo Agens'
    Copyright         = '(C) 2026 Homo Agens. AGPL-3.0-or-later.'
    Description       = 'One command, many projects: chooses a Pragma project, sets this window up for it, and gets out of the way.'
    PowerShellVersion = '5.1'
    FunctionsToExport = @('Start-Pragma')
    AliasesToExport   = @('pragma')
    CmdletsToExport   = @()
    VariablesToExport = @()
}
