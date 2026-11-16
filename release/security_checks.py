"""Offline regression checks for the trust boundaries used by the desktop app."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from PIL import Image

APP = Path(__file__).resolve().parents[1] / "app"
sys.path[:0] = [str(APP), str(APP / "caption")]
workspace = tempfile.TemporaryDirectory()
os.environ["HYDRA_DATA_DIR"] = workspace.name

import comparar
import componentes
from configuracao import discover, write_json
from core import AIConfig, authorized_base, confirm_inference_endpoint, inference_json
from dataset import Dataset, csv_text
from local_files import project_path
from net_limits import NoRedirectSession, response_json
from regioes import LIMIT, SIZE, caption_guide, pack_mask, read_regions, unpack_mask
from revisao import import_project
from sources import SourceClient, media_url_ok


class SecurityChecks(unittest.TestCase):
    def test_caption_destinations(self):
        local, on_device = authorized_base("http://localhost:8080/v1", "")
        self.assertEqual((local, on_device), ("http://127.0.0.1:8080/v1", True))
        remote = "https://example.invalid/inference"
        cfg = AIConfig("Ollama (local)", "vision", "", "", "", ollama_url=remote)
        with self.assertRaises(ValueError):
            authorized_base(remote, cfg.approved_endpoint)
        with self.assertRaises(ValueError):
            confirm_inference_endpoint(cfg, lambda *_: False)
        confirm_inference_endpoint(cfg, lambda *_: True)
        self.assertEqual(authorized_base(remote, cfg.approved_endpoint), (remote, False))
        with self.assertRaises(ValueError):
            authorized_base(remote.replace("https:", "http:"), cfg.approved_endpoint)
        with self.assertRaises(ValueError):
            authorized_base(remote + "/different", cfg.approved_endpoint)

    def test_local_transport(self):
        with patch("core.NoRedirectSession") as factory:
            session = factory.return_value.__enter__.return_value
            response = session.request.return_value.__enter__.return_value
            response.status_code = 307
            with self.assertRaises(ValueError):
                inference_json("POST", "http://127.0.0.1:8080", loopback=True)
            self.assertFalse(session.trust_env)
            self.assertFalse(session.request.call_args.kwargs["allow_redirects"])

    def test_redirect_body_is_not_consumed(self):
        import requests
        from requests.adapters import BaseAdapter

        class Redirect(BaseAdapter):
            def send(self, request, **kwargs):
                reply = requests.Response()
                reply.status_code = 302
                reply.headers["Location"] = "https://example.invalid/other"
                reply.raw = Mock(spec=['stream','close','release_conn'])
                reply.request = request
                return reply
            def close(self):
                pass

        with NoRedirectSession() as session:
            session.trust_env = False
            session.mount("https://", Redirect())
            with session.get("https://example.invalid", allow_redirects=False, stream=True) as reply:
                self.assertEqual(reply.status_code, 302)
                reply.raw.stream.assert_not_called()
        self.assertTrue(media_url_ok("https://static1.e621.net/image.png", "e621"))
        self.assertFalse(media_url_ok("https://example.invalid" + chr(92) + ".e621.net/file", "e621"))

    def test_metadata_budget(self):
        response = Mock(headers={})
        response.iter_content.return_value = [b'{"a":', b'1}']
        self.assertEqual(response_json(response, 7), {"a":1})
        with self.assertRaises(ValueError):
            response_json(response, 6)
        response.headers = {"Content-Length": "8"}
        with self.assertRaises(ValueError):
            response_json(response, 7)

    def test_source_identity(self):
        client = SourceClient(username="example_user")
        with patch.object(client.session, "get") as get:
            get.return_value = Mock(is_redirect=False, status_code=200)
            client.request("https://e621.net/posts.json")
            self.assertIn("example_user", get.call_args.kwargs["headers"]["User-Agent"])
            client.request("https://danbooru.donmai.us/posts.json")
            self.assertNotIn("example_user", str(get.call_args.kwargs["headers"]))
            self.assertNotIn("example_user", str(client.session.headers))
        client.session.close()

    def test_paths_and_masks(self):
        root = Path(workspace.name)
        self.assertEqual(project_path(root, "frames/sample.png", nested=True), root/"frames/sample.png")
        for path in ("/outside", r"C:\foreign", "../other", "a:b", "a/b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                project_path(root, path)
        encoded = pack_mask(Image.new("1", (SIZE, SIZE), 1))
        self.assertEqual(unpack_mask(encoded).size, (SIZE, SIZE))
        note = {"mask":encoded, "note":"test", "confirmed":True}
        guide = {"crop":[0.5, 0.5, 1], "regions":[note] * LIMIT}
        self.assertEqual(len(read_regions({"caption_regions":guide})), LIMIT)
        guide["regions"].append(note)
        with self.assertRaises(ValueError):
            caption_guide(root/"unused.png", {"caption_regions":guide}, "Recortar 1:1")

    def test_csv(self):
        self.assertEqual(csv_text("cat, sky"), "cat, sky")
        self.assertEqual(csv_text("=1+1"), "'=1+1")
        self.assertEqual(csv_text(12), 12)

    def test_catalog_import(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = Dataset(root/"original")
            try:
                sample = root/"sample.png"
                Image.new("RGB", (32, 32), "blue").save(sample)
                key, _ = source.import_file(sample)
                source.items[key]["krea"] = "blue square"
                source.save_one(key)
                (source.images/"unreferenced.txt").write_text("skipped", encoding="utf8")
            finally:
                source.close()
            project = import_project(root/"original", "Krea2")
            try:
                self.assertEqual(project.items[key]["krea"], "blue square")
                self.assertTrue(project.path_for(project.items[key]).is_file())
                self.assertFalse((project.images/"unreferenced.txt").exists())
            finally:
                project.close()

    def test_import_folder_and_host_preferences(self):
        from local_files import folder_files
        from core import atomic_json
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            root = folder/"catalog"
            root.mkdir()
            foreign = folder/"external"
            atomic_json(root/"configuracao.json", {"biblioteca":str(foreign), "extrator":{"ffprobe":"unselected"}})
            project = Dataset(root)
            try:
                self.assertIsNone(project.library)
                self.assertFalse(project.settings.ffprobe)
            finally:
                project.close()
            (folder/"notes.txt").touch()
            self.assertEqual(list(folder_files(folder,True,root)), [folder/"notes.txt"])

    def test_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            link = root/"link"
            try:
                link.symlink_to(root/"document.txt")
            except OSError:
                if os.name != "nt":
                    raise
                import _winapi
                target = root/"target"
                target.mkdir()
                _winapi.CreateJunction(str(target),str(link))
            with self.assertRaises(ValueError):
                project_path(root, "link")

    def test_comparison_manifest_and_custom_model(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp)
            run = comparar.LORAS/"Krea2"/"example"
            manifest = {"treino":r"Krea2\example", "perfil":"Krea2", "versoes":[{"arquivo":""}],
                        "res":640, "imagens":{"0-0":"sample.png"}}
            write_json(dest/"grade.json", manifest)
            grade = comparar.load_grade(dest)
            self.assertEqual(comparar.LORAS/grade["treino"], run)
            model = dest/"sample.safetensors"
            model.touch()
            with self.assertRaises(ValueError):
                comparar.approved_model(str(model))
            self.assertTrue(comparar.approved_model(comparar.remember_model(model)).samefile(model))
            manifest["imagens"]["0-0"] = "../another.png"
            write_json(dest/"grade.json",manifest)
            with self.assertRaises(ValueError):
                comparar.load_grade(dest)

    def test_engine_cache_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root/"cache"/"revision.zip"
            archive.parent.mkdir()
            with ZipFile(archive, "w") as z:
                z.writestr("engine-revision/README", "fixture")
            allowed = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.object(componentes,"CACHE",archive.parent), patch.dict(componentes.ENGINE_SHA256,{("fixture","revision"):allowed}):
                componentes.source("fixture","revision",root/"installed")
                self.assertTrue((root/"installed/README").is_file())
                archive.write_bytes(b"changed")
                with self.assertRaises(RuntimeError):
                    componentes.source("fixture","revision",root/"other")
                self.assertFalse((root/"other").exists())

    def test_existing_managed_install_requires_verified_runtime(self):
        import configuracao
        with patch.object(configuracao, "read_json", return_value={"treino":str(componentes.COMP/"treino")}):
            configuracao.discover.cache_clear()
            self.assertEqual(Path(configuracao.discover()["treino"]), componentes.MANAGED_TRAIN)
        configuracao.discover.cache_clear()

    def test_output_name_and_weight_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            model = folder/"fixture.safetensors"
            model.write_bytes(b"sample")
            asset = {"name":model.name, "size":6, "sha":hashlib.sha256(b"sample").hexdigest()}
            self.assertTrue(componentes.reusable(asset, {"modelos":tmp}, verify=True))
            model.write_bytes(b"edited")
            with self.assertRaises(RuntimeError):
                componentes.reusable(asset, {"modelos":tmp}, verify=True)

    def test_engine_defaults(self):
        defaults = discover()
        self.assertEqual(Path(defaults["treino"]), componentes.MANAGED_TRAIN)
        self.assertEqual(Path(defaults["comfy"]), componentes.MANAGED_COMFY)


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        workspace.cleanup()
