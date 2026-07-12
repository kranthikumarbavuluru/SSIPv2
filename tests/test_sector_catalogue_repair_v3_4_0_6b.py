import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("agent",ROOT/"scripts"/"sector_catalogue_repair_v3_4_0_6b.py")
MOD=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MOD)
RULES=__import__("json").loads((ROOT/"config"/"sector_rules_v3_4_0_6b.json").read_text())

def sector(row): return MOD.classify(row,RULES,False,0)["primary_sector"]

def test_nidhi(): assert sector({"scheme_name":"NIDHI PRAYAS","objectives":"prototype support for startups"})==MOD.CROSS_INNOVATION

def test_finance(): assert sector({"scheme_name":"Credit Guarantee Scheme for Startups","benefits":"credit guarantee across sectors"})==MOD.CROSS_FINANCE

def test_agri(): assert sector({"scheme_name":"AgriTech","objectives":"farm agriculture technology"})=="Agriculture & AgriTech"

def test_biotech(): assert sector({"scheme_name":"Biotech Innovation","objectives":"biotechnology life sciences"})=="Biotechnology & Life Sciences"

def test_no_blank(): assert sector({"scheme_name":"General support"})==MOD.SECTOR_AGNOSTIC
