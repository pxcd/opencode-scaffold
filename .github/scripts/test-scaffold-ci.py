"""Portable hosted subset; preserve the original workstation integration test."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import test_newoc

@unittest.skip("Workstation-only newpy ~/.zshrc integration; run original suite locally")
def local_newpy(self):
    pass

test_newoc.ScaffoldTests.test_newpy_then_newoc_here=local_newpy
suite=unittest.defaultTestLoader.loadTestsFromModule(test_newoc)
result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
