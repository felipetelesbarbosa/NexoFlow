import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

import maintenance as m
import bridge


class StorageSafetyTests(unittest.TestCase):
    def test_request_never_accepts_path_or_command(self):
        good={"id":"a"*32,"acao":"limpeza"}
        self.assertEqual(m.validate_request(json.dumps(good).encode()),good)
        for obj in ({**good,"path":"/"}, {**good,"acao":"rm"}, {**good,"id":"../abc"},
                    {**good,"acao":"/etc"}):
            with self.assertRaises(ValueError):
                m.validate_request(json.dumps(obj).encode())

    def test_cost_threshold(self):
        self.assertEqual(m.cost_estimate(7_900_000_000)["nivel"],"normal")
        self.assertEqual(m.cost_estimate(8_000_000_000)["nivel"],"atencao")
        self.assertEqual(m.cost_estimate(10_000_000_001)["nivel"],"alerta")
        self.assertEqual(m.cost_estimate(21_728_761_991)["estimativa_excedente_usd_mes_se_constante"],0.18)

    def test_retention_only_authorized_tags_and_latest_protected(self):
        a,b,c,d,e=[str(i)*64 for i in range(1,6)]
        def item(i,date,tags):return {"id":i,"time":date,"tags":tags}
        snaps=[item(a,"2026-11-01",["nexoflow-diario"]),
               item(b,"2026-11-02",["nexoflow-diario"]),
               item(c,"2026-11-03",["nexoflow-diario","nexoflow-policy-v1"]),
               item(d,"2026-11-04",["nexoflow-arquivo-historico"]),
               item(e,"2026-11-05",["nexoflow-diario","manual"])]
        ids,protected=m.approved_retention_ids(snaps,[{"keep":[snaps[1],snaps[2]],"remove":[snaps[0]]}])
        self.assertEqual(ids,[a])
        self.assertEqual(protected,{c,d,e})
        for x in (snaps[2],snaps[3],snaps[4]):
            with self.assertRaises(ValueError):
                m.approved_retention_ids(snaps,[{"keep":[snaps[1]],"remove":[x]}])
        with self.assertRaises(ValueError):
            m.approved_retention_ids(snaps,[{"keep":[],"remove":[snaps[0]]}])

    def test_archive_only_if_every_file_matches(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); dest=root/"extracted";dest.mkdir()
            (dest/"code.txt").write_bytes(b"same")
            a=root/"source.tar.gz"
            with tarfile.open(a,"w:gz") as tf:
                t=tarfile.TarInfo("repo/code.txt");t.size=4;tf.addfile(t,io.BytesIO(b"same"))
            self.assertTrue(m.archive_matches(a,dest))
            (dest/"code.txt").write_bytes(b"diff")
            self.assertFalse(m.archive_matches(a,dest))
            (dest/"code.txt").unlink()
            self.assertFalse(m.archive_matches(a,dest))

    def test_bridge_auth(self):
        self.assertTrue(bridge.authenticated("Bearer private","private"))
        self.assertFalse(bridge.authenticated("Bearer wrong","private"))
        self.assertFalse(bridge.authenticated("Bearer ",""))

if __name__=="__main__":unittest.main()
