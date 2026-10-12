import io, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from silhouette.Graphtec import SilhouetteCameo


class _Done(Exception):
    pass


class _FakeTransport:
    """Answers each mark search (TB123) with the next scripted reply."""

    def __init__(self, replies):
        self.replies, self.sent, self.pending = list(replies), [], []

    def write_bytes(self, data, timeout=None):
        self.sent.append(bytes(data))
        if bytes(data).startswith(b"TB123"):
            self.pending.append(self.replies.pop(0))
        return len(data)

    def read_bytes(self, size, timeout):
        if self.pending and timeout > 100:
            return self.pending.pop(0)
        raise TimeoutError()

    def close(self):
        pass


def _register(replies, retries=4):
    log = io.StringIO()
    dev = SilhouetteCameo(log=log, dry_run=True, force_hardware="Silhouette_Portrait3")
    dev.dry_run = False
    dev.transport = _FakeTransport(replies)

    def stop(*a, **k):
        raise _Done()
    dev.plot_cmds = stop
    try:
        dev.plot(pathlist=[[(20, 20), (30, 30)]], mediawidth=210, mediaheight=297,
                 regmark=True, regsearch=True, regwidth=180, reglength=277,
                 regoriginx=10, regoriginy=10, regsearch_margin=0,
                 reg_mark_length=25, reg_mark_thickness=1.0,
                 regsearch_retries=retries, regsearch_jitter=1.5)
    except _Done:
        return True, dev
    except ValueError:
        return False, dev
    return None, dev


class TestRegmarkRetry(unittest.TestCase):

    def test_retries_until_found(self):
        ok, dev = _register([b"   -1\x03", b"    1\x03", b"    0\x03"])
        self.assertTrue(ok)
        searches = [c for c in dev.transport.sent if c.startswith(b"TB123")]
        self.assertEqual(len(searches), 3)
        self.assertEqual(len(set(searches)), 3)          # each attempt shifted

    def test_gives_up(self):
        ok, dev = _register([b"    1\x03"] * 5)
        self.assertFalse(ok)
        self.assertEqual(len([c for c in dev.transport.sent if c.startswith(b"TB123")]), 5)

    def test_mark_size_sent_to_cutter(self):
        ok, dev = _register([b"    0\x03"])
        self.assertIn(b"TB51,500\x03", dev.transport.sent)   # 25 mm
        self.assertIn(b"TB53,20\x03", dev.transport.sent)    # 1 mm


class TestRegmarkTestMode(unittest.TestCase):

    def test_counts_found_and_never_cuts(self):
        log = io.StringIO()
        dev = SilhouetteCameo(log=log, dry_run=True, force_hardware="Silhouette_Portrait3")
        dev.dry_run = False
        dev.transport = _FakeTransport([b"    0\x03", b"   -1\x03", b"    0\x03", b"    1\x03"])
        result = dev.regmark_test(runs=4, reglength=277, regwidth=180, regoriginx=10, regoriginy=10,
                                  reg_mark_length=20, reg_mark_thickness=1.0, pause=0)
        self.assertEqual(result["found"], 2)
        self.assertEqual([r["answer"] for r in result["runs"]], ["0", "-1", "0", "1"])
        self.assertIn("found 2 of 4", result["summary"])
        searches = [c for c in dev.transport.sent if c.startswith(b"TB123")]
        self.assertEqual(len(searches), 4)
        self.assertEqual(len(set(searches)), 1)          # always the same position
        self.assertIn(b"TB53,20\x03", dev.transport.sent)   # 1 mm thickness
        self.assertFalse(any(c[:1] == b"D" for c in dev.transport.sent))   # nothing drawn


if __name__ == "__main__":
    unittest.main()

class TestRegmarkSweep(unittest.TestCase):

    def _dev(self, replies):
        dev = SilhouetteCameo(log=io.StringIO(), dry_run=True, force_hardware="Silhouette_Portrait3")
        dev.dry_run = False
        dev.transport = _FakeTransport(replies)
        return dev

    def test_sweep_stops_at_first_hit(self):
        dev = self._dev([b"   -1\x03"] * 5 + [b"    0\x03"] + [b"   -1\x03"] * 30)
        r = dev.regmark_test(reglength=277, regwidth=180, regoriginx=10, regoriginy=10,
                             pause=0, sweep_step=2.0)
        self.assertEqual(len(r["runs"]), 6)
        self.assertEqual((r["runs"][0]["dx"], r["runs"][0]["dy"]), (0.0, 0.0))
        self.assertIn("FOUND with the search shifted", r["summary"])
        searches = [c for c in dev.transport.sent if c.startswith(b"TB123")]
        self.assertEqual(len(set(searches)), 6)            # all positions differ
        self.assertEqual(searches[0], b"TB123,5540,3600,200,200\x03")

    def test_sweep_stops_when_cutter_ejects(self):
        dev = self._dev([b"   -1\x03", b"    1\x03"] + [b"   -1\x03"] * 30)
        r = dev.regmark_test(reglength=277, regwidth=180, regoriginx=10, regoriginy=10,
                             pause=0, sweep_step=2.0)
        self.assertEqual(len(r["runs"]), 2)
        self.assertIn("gave up", r["summary"])

    def test_sweep_covers_5x5(self):
        dev = self._dev([b"   -1\x03"] * 25)
        r = dev.regmark_test(reglength=277, regwidth=180, regoriginx=10, regoriginy=10,
                             pause=0, sweep_step=2.0)
        self.assertEqual(len(r["runs"]), 25)
        self.assertEqual(r["found"], 0)

