from pygls.server import LanguageServer
from lsprotocol import types
from pygls.workspace import Document
import logging
import re
from typing import Dict, Tuple, List, Optional

# configure logging (for debug)
logging.basicConfig(filename='myopl-lsp.log', level=logging.DEBUG)
logger = logging.getLogger(__name__)

server = LanguageServer("myopl-lsp", "v0.1")

# language keywords
KEYWORDS = [
    'VAR', 'AND', 'OR', 'NOT', 'IF', 'ELIF', 'ELSE', 'FOR', 'TO',
    'STEP', 'WHILE', 'FUN', 'THEN', 'END', 'RETURN', 'CONTINUE', 'BREAK'
]

# builtin functions with documentation
BUILTIN_FUNCTIONS = {
    "print": "Prints the given values",
    "print_ret": "Prints and returns the given values",
    "input": "Gets input from user",
    "input_int": "Gets integer input from user",
    "clear": "Clears the screen",
    "is_number": "Checks if value is a number",
    "is_string": "Checks if value is a string",
    "is_list": "Checks if value is a list",
    "is_function": "Checks if value is a function",
    "append": "Appends item to list",
    "pop": "Removes and returns item from list",
    "extend": "Extends list with another list",
    "len": "Returns length of collection",
    "run": "Runs code from string"
}

# track document states
document_states: Dict[str, Dict] = {}

# document_states = {
# "test.myopl": {
#  "text": "VAR myVar = 4\nmyVar\NIF",
#  "variables": {
# "myAge": (line = 0, column 4)
# }
# }
# }


def parse_document(text: str) -> Tuple[Dict[str, Tuple[int, int, str]], Dict[str, str], List[types.Diagnostic]]:
    variables = {}
    diagnostics = []
    lines = text.splitlines()

    # collect all variables and their values
    for line_num, line in enumerate(lines):
        line = line.strip()
        if line.upper().startswith("VAR "):
            # split into VAR, name, and the rest
            parts = line.split(maxsplit=2)
            if len(parts) >= 2:
                var_name = parts[1]
                var_value = parts[2] if len(parts) > 2 else "undefined"
                col = line.find(var_name)
                variables[var_name] = (line_num, col, var_value)

    # validate all identifiers
    valid_identifiers = set(variables.keys()).union(
        set(BUILTIN_FUNCTIONS.keys()))
    for line_num, line in enumerate(lines):
        line = line.strip()
        if not line or line.startswith('//'):
            continue

        for match in re.finditer(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', line):
            word = match.group(1)
            if not (word in KEYWORDS or
                    word in valid_identifiers or
                    word.upper() in KEYWORDS or
                    word in BUILTIN_FUNCTIONS):
                col = match.start()
                diagnostics.append(types.Diagnostic(
                    range=types.Range(
                        start=types.Position(line=line_num, character=col),
                        end=types.Position(
                            line=line_num, character=col + len(word))
                    ),
                    message=f"Undefined identifier: '{word}'",
                    severity=types.DiagnosticSeverity.Error,
                    source="MyOPL"
                ))

    return variables, diagnostics


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
def definition(ls, params: types.DefinitionParams):
    uri = params.text_document.uri
    if uri not in document_states:
        return None

    doc = ls.workspace.get_document(uri)
    pos = params.position
    line = doc.lines[pos.line]

    # find word at cursor position
    for match in re.finditer(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', line):
        if match.start() <= pos.character <= match.end():
            var_name = match.group(1)
            if var_name in document_states[uri]['variables']:
                line_num, col, _ = document_states[uri]['variables'][var_name]
                return types.Location(
                    uri=uri,
                    range=types.Range(
                        start=types.Position(line=line_num, character=col),
                        end=types.Position(
                            line=line_num, character=col + len(var_name))
                    )
                )
    return None


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(ls, params: types.HoverParams):
    uri = params.text_document.uri
    if uri not in document_states:
        return None

    doc = ls.workspace.get_document(uri)
    pos = params.position
    line = doc.lines[pos.line]

    # find word at hover position
    for match in re.finditer(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', line):
        if match.start() <= pos.character <= match.end():
            word = match.group(1)

            # check for variables
            if word in document_states[uri]['variables']:
                _, _, value = document_states[uri]['variables'][word]
                return types.Hover(
                    contents=types.MarkupContent(
                        kind=types.MarkupKind.Markdown,
                        value=f"**Variable**: `{word}`\n\n**Value**: `{value}`"
                    ),
                    range=types.Range(
                        start=types.Position(
                            line=pos.line, character=match.start()),
                        end=types.Position(
                            line=pos.line, character=match.end())
                    )
                )

            # check for builtin functions
            if word in BUILTIN_FUNCTIONS:
                return types.Hover(
                    contents=types.MarkupContent(
                        kind=types.MarkupKind.Markdown,
                        value=f"**Built-in function**: `{word}`\n\n{BUILTIN_FUNCTIONS[word]}"
                    )
                )

            # check for keywords
            if word.upper() in KEYWORDS:
                return types.Hover(
                    contents=types.MarkupContent(
                        kind=types.MarkupKind.Markdown,
                        value=f"**Keyword**: `{word.upper()}`"
                    )
                )

    return None


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls, params: types.DidOpenTextDocumentParams):
    uri = params.text_document.uri
    text = params.text_document.text
    variables, diagnostics = parse_document(text)
    document_states[uri] = {'text': text, 'variables': variables}
    server.publish_diagnostics(uri, diagnostics)
    logger.info(f"Document opened: {uri}")


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls, params: types.DidChangeTextDocumentParams):
    uri = params.text_document.uri
    doc = ls.workspace.get_document(uri)
    current_text = doc.source

    variables, diagnostics = parse_document(current_text)
    document_states[uri] = {'text': current_text, 'variables': variables}
    server.publish_diagnostics(uri, diagnostics)
    logger.info(f"Document updated: {uri}")


@server.feature(types.TEXT_DOCUMENT_COMPLETION)
def completions(ls, params: types.CompletionParams):
    uri = params.text_document.uri
    items = []

    # add variables if document exists
    if uri in document_states:
        items.extend(
            types.CompletionItem(
                label=var_name,
                kind=types.CompletionItemKind.Variable,
                documentation=f"Value: {var_info[2]}",
                detail=f"Variable: {var_name} = {var_info[2]}"
            )
            for var_name, var_info in document_states[uri]['variables'].items()
        )

    # add keywords
    items.extend(
        types.CompletionItem(
            label=kw,
            kind=types.CompletionItemKind.Keyword,
            documentation=f"MyOPL keyword",
            insert_text=kw.lower()
        )
        for kw in KEYWORDS
    )

    # add builtin functions
    items.extend(
        types.CompletionItem(
            label=func,
            kind=types.CompletionItemKind.Function,
            documentation=BUILTIN_FUNCTIONS[func],
            insert_text=f"{func}($0)",
            insert_text_format=types.InsertTextFormat.Snippet
        )
        for func in BUILTIN_FUNCTIONS
    )

    logger.info(f"Providing {len(items)} completions")
    return items


if __name__ == "__main__":
    logger.info("Starting MyOPL language server")
    server.start_io()
