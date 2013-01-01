import os
import re
import sys

import astnodes as ast
import rewrite.terms as aterm

# Precompiled modules
try:
    import dlex
    import dyacc
except ImportError:
    pass

from functools import partial
from rewrite.plyhacks import yaccfrom, lexfrom

#------------------------------------------------------------------------
# Errors
#------------------------------------------------------------------------

syntax_error = """

  File {filename}, line {lineno}
    {line}
    {pointer}

ATermSyntaxError: {msg}
"""

#------------------------------------------------------------------------
# Lexer
#------------------------------------------------------------------------

combinators = [
    'fail' ,
    'id'   ,
    '<+'   ,
    ';'    ,
]

tokens = (
    'NAME', 'INT', 'DOUBLE', 'ARROW', 'STRING', 'COMB' #, 'CLAUSE'
)

literals = [
    ';',
    ',',
    '|',
    ':',
    '=',
    '(',
    ')',
    '{',
    '}',
    '[',
    ']',
]

t_NAME   = r'[a-zA-Z_][a-zA-Z0-9_]*'
t_ignore = '\x20\x09\x0A\x0D'

# dynamically generate the regex for the Combinator token from
# the keys of the combinator dictionary
t_COMB  = '|'.join(map(re.escape, combinators))

unquote = re.compile('"(?:[^\']*)\'|"([^"]*)"')

def t_NEWLINE(t):
   r'\n'
   t.lexer.lineno += 1

def t_DOUBLE(t):
    r'\d+\.(\d+)?'
    t.value = float(t.value)
    return t

def t_INT(t):
    r'\d+'
    try:
        t.value = int(t.value)
    except ValueError:
        print("Integer value too large %d", t.value)
        t.value = 0
    return t

def t_ARROW(t):
    r'->'
    return t

def t_STRING(t):
    r'"([^"\\]|\\.)*"'
    t.value = t.value.encode('ascii')
    t.value = unquote.findall(t.value)[0]
    return t

#def t_CLAUSE(t):
    #r'not|rec'
    #return t

def t_error(t):
    print("Unknown token '%s'" % t.value[0])
    t.lexer.skip(1)

#--------------------------------

#------------------------------------------------------------------------
# Parser
#------------------------------------------------------------------------

class RewriteSyntaxError(Exception):
    def __init__(self, lineno, col_offset, filename, text, msg=None):
        self.lineno     = lineno
        self.col_offset = col_offset
        self.filename   = filename
        self.text       = text
        self.msg        = msg or 'invalid syntax'

    def __str__(self):
        return syntax_error.format(
            filename = self.filename,
            lineno   = self.lineno,
            line     = self.text.split('\n')[self.lineno],
            pointer  = ' '*self.col_offset + '^',
            msg      = self.msg
        )

start = 'definitions'

def p_definitions1(p):
    '''definitions : definitions rule
                   | definitions strategy'''
    p[0] = p[1] + [p[2]]

def p_definitions2(p):
    '''definitions : rule
                   | strategy'''
    p[0] = [p[1]]

#--------------------------------

def p_rule(p):
    '''rule : NAME ':' value ARROW value'''
    p[0] = ast.RuleNode(p[1],p[3],p[5])

#--------------------------------

def p_strategy(p):
    '''strategy : NAME '=' strategy_value'''
    combs, args = p[3]
    p[0] = ast.StrategyNode(p[1], combs, args)

def p_strategy_value1(p):
    '''strategy_value : strategy_value COMB strategy_value'''

    if isinstance(p[1], ast.StrategyNode):
        p[0] = (p[2], [p[1]] + p[3])
    elif isinstance(p[3], ast.StrategyNode):
        p[0] = (p[2], p[1] + [p[3]])
    else:
        p[0] = (p[2], [p[1],p[3]])

def p_strategy_value2(p):
    '''strategy_value : value'''
    p[0] = [p[1]]

#--------------------------------

def p_expr(p):
    '''expr : value'''
    p[0] = p[1]

#--------------------------------

def p_value(p):
    """value : term
             | appl
             | list
             | tuple
             | string
             | empty"""
    p[0] = p[1]

#--------------------------------

def p_term_double(p):
    "term : DOUBLE"
    p[0] = aterm.areal(p[1])

def p_term_int(p):
    "term : INT"
    p[0] = aterm.aint(p[1])

def p_term_term(p):
    "term : NAME"
    p[0] = aterm.aterm(p[1], None)

#--------------------------------

def p_appl(p):
    "appl : term '(' appl_value ')' "
    p[0] = aterm.aappl(p[1], p[3])

def p_appl_value1(p):
    "appl_value : expr"
    if p[1]:
        p[0] = [p[1]]
    else:
        p[0] = []

def p_appl_value2(p):
    "appl_value : appl_value ',' appl_value"
    p[0] = p[1] + p[3]

#--------------------------------

def p_list(p):
    "list : '[' list_value ']' "
    p[0] = aterm.alist(p[2])

def p_list_value1(p):
    "list_value : expr"
    if p[1]:
        p[0] = [p[1]]
    else:
        p[0] = []

def p_list_value2(p):
    "list_value : list_value ',' list_value"
    p[0] = p[1] + p[3]

#--------------------------------

def p_tuple(p):
    "tuple : '(' tuple_value ')' "
    p[0] = aterm.atupl(p[2])

def p_tuple_value1(p):
    "tuple_value : expr"
    if p[1]:
        p[0] = [p[1]]
    else:
        p[0] = []

def p_tuple_value2(p):
    "tuple_value : tuple_value ',' tuple_value"
    p[0] = p[1] + p[3]

#--------------------------------

def p_string(p):
    "string : STRING"
    p[0] = aterm.astr(p[1])

#--------------------------------

def p_empty(t):
    "empty : "
    pass

#--------------------------------

def p_error(p):
    if p:
        raise RewriteSyntaxError(
            p.lineno,
            p.lexpos,
            '<stdin>',
            p.lexer.lexdata,
        )
    else:
        raise SyntaxError("Syntax error at EOF")


def load_parser(debug=False):
    if debug:
        from ply import lex, yacc
        path = os.path.abspath(__file__)
        dir_path = os.path.dirname(path)
        lexer = lex.lex(lextab="dlex", outputdir=dir_path, optimize=1)
        parser = yacc.yacc(tabmodule='dyacc',outputdir=dir_path,
                write_tables=1, debug=0, optimize=1)
        return partial(parser.parse, lexer=lexer)
    else:
        module = sys.modules[__name__]
        lexer = lexfrom(module, dlex)
        parser = yaccfrom(module, dyacc, lexer)

        # curry the lexer into the parser
        return partial(parser.parse, lexer=lexer)

def dslparse(pattern):
    parse = load_parser(True)
    return parse(pattern)