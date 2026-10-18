"""Explicit trusted-broker identity for legacy domain tests, never production."""
import atexit,os,tempfile
from pathlib import Path
if not os.environ.get('MC_DB'):
    _temporary=tempfile.TemporaryDirectory(prefix='bm318d-test-bootstrap-',ignore_cleanup_errors=True)
    os.environ['MC_DB']=str(Path(_temporary.name)/'bootstrap.sqlite3')
    atexit.register(_temporary.cleanup)

def broker_fixture(mc):
    import mc_security
    return mc_security.use(mc_security.operator(mc.TOKEN,mc.TOKEN,mc.ADMIN_TOKEN,mc.ADMIN_TOKEN))
