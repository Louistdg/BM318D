"""Trusted prompt ingestion must reject linked external synthetic secrets."""
import os,tempfile,unittest,subprocess
from pathlib import Path
import mc_agent

class ContextV23(unittest.TestCase):
    def test_plain_workspace_remains_readable(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'main.py').write_text('print(1)')
            self.assertIn('print(1)',mc_agent.lire_contexte(root))

    def test_external_hardlink_is_rejected_before_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);workspace=root/'workspace';workspace.mkdir()
            secret=root/'secret.txt';secret.write_text('synthetic-only')
            os.link(secret,workspace/'linked.txt')
            with self.assertRaises(ValueError):mc_agent.lire_contexte(workspace)

    def test_external_directory_link_is_rejected_before_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);workspace=root/'workspace';workspace.mkdir()
            outside=root/'outside';outside.mkdir();(outside/'secret.txt').write_text('synthetic-only')
            link=workspace/'linked'
            if os.name=='nt':
                result=subprocess.run(['cmd.exe','/c','mklink','/J',str(link),str(outside)],capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
            else:link.symlink_to(outside,target_is_directory=True)
            try:
                with self.assertRaises(ValueError):mc_agent.lire_contexte(workspace)
            finally:
                if os.name=='nt':os.rmdir(link)
                else:link.unlink()

if __name__=='__main__':unittest.main(verbosity=2)
