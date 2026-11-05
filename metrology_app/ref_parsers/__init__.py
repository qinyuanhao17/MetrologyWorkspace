"""REF vendor readers adapted from the supplied Summarize REF example."""
from .kla_parser import parse_kla_file
from .nova_parser import parse_nova_file
from .pmish_parser import parse_pmish_file

PARSER_MAP = {"KLA": parse_kla_file, "NOVA": parse_nova_file, "PMISH": parse_pmish_file}
