#!/usr/bin/env python3
"""agent-commons 协议安全、状态投影与 CI 门禁测试集（零私钥入库）。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from canonical import canonical_bytes  # noqa: E402
from render_state import render_state_markdown  # noqa: E402


def _gen_ed25519_keypair(directory: Path, name: str) -> tuple[Path, str]:
    priv = directory / f"{name}.key"
    pub = directory / f"{name}.pub.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(priv)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(priv), "-pubout", "-out", str(pub)],
        check=True,
        capture_output=True,
        text=True,
    )
    return priv, pub.read_text(encoding="utf-8")


def _write_registry(path: Path, entries: list[dict]) -> None:
    import yaml

    path.write_text(yaml.safe_dump({"agents": entries}, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _make_agent_entry(
    *,
    agent_id: str,
    github_user: str,
    key_id: str,
    pub_pem: str,
    scope: list[str] | None = None,
    expires: str = "2027-01-01",
    status: str = "active",
    state_keys: list[str] | None = None,
) -> dict:
    entry = {
        "agent_id": agent_id,
        "github_user": github_user,
        "key_id": key_id,
        "algorithm": "ed25519",
        "public_key_pem": pub_pem,
        "scope": scope if scope is not None else [f"inbox/{agent_id}/", "transitions/"],
        "expires": expires,
        "status": status,
    }
    if state_keys is not None:
        entry["state_keys"] = state_keys
    return entry


def _make_transition(
    *,
    tid: str,
    agent: str,
    key_id: str,
    state_key: str,
    state_value: object,
    version: int,
    supersedes: str = "",
    verdict: str = "VERIFIED_CHANGE",
    evidence_locator: str = "evidence/e1.txt",
    evidence_sha256: str = "",
    observed_at: str = "2026-11-24T12:00:00+08:00",
) -> dict:
    return {
        "protocol": "agent-os/world-state-transition",
        "protocol_version": "0.1",
        "transition_id": tid,
        "supersedes": supersedes,
        "identity": {"agent": agent, "key_id": key_id},
        "signature": {"algorithm": "ed25519", "value": ""},
        "observed_at": observed_at,
        "claim": {
            "agent": agent,
            "statement": f"Update {state_key} to v{version}",
            "target": state_key,
            "intervention": "automated protocol test",
        },
        "evidence": [
            {
                "type": "file",
                "locator": evidence_locator,
                "sha256": evidence_sha256,
                "observed_at": observed_at,
            }
        ],
        "verification": {
            "verdict": verdict,
            "gate_version": "world-change-gate/2026-09-20",
            "verified_by": agent,
            "before": "prev",
            "after": "next",
            "attribution": "direct test transition",
            "durability": "committed in git",
        },
        "state": {
            "key": state_key,
            "value": state_value,
            "version": version,
            "previous_version": version - 1,
        },
        "receipt": {
            "id": f"receipt-{tid}",
            "transition_id": tid,
            "summary": f"{state_key} -> v{version}",
            "verified_by": agent,
            "evidence_refs": [evidence_sha256] if evidence_sha256 else [],
        },
        "permissions": "reserved:v0.2",
        "event": "reserved:v0.3",
    }


def _sign_file(priv_key: Path, json_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPTS_DIR / "sign.py"), "--key", str(priv_key), "--in", str(json_path)],
        capture_output=True,
        text=True,
    )


def _verify_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPTS_DIR / "verify.py"), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _render_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPTS_DIR / "render_state.py"), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _ci_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPTS_DIR / "ci_check.py"), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _git(cwd: Path, args: list[str]) -> str:
    res = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout


class CanonicalTests(unittest.TestCase):
    def test_utf16be_sort_and_signature_algorithm_bound(self) -> None:
        # U+10000 in UTF-8 is F0 90 80 80, in UTF-16-BE is D8 00 DC 00 (< E0 00)
        # UTF-16-BE puts \U00010000 BEFORE \uE000; UTF-8 code-point puts \uE000 first.
        env = {
            "signature": {"algorithm": "ed25519", "value": "ignored"},
            "\uE000": 1,
            "\U00010000": 2,
        }
        raw = canonical_bytes(env).decode("utf-8")
        self.assertLess(raw.index('"signature"'), raw.index('"\U00010000"'))
        self.assertLess(raw.index('"\U00010000"'), raw.index('"\uE000"'))
        self.assertIn('"algorithm":"ed25519"', raw)
        self.assertNotIn("ignored", raw)

    def test_floats_forbidden(self) -> None:
        env = {
            "signature": {"algorithm": "ed25519", "value": ""},
            "state": {"value": 1.5},
        }
        with self.assertRaises(ValueError):
            canonical_bytes(env)


class VerifyAndProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.td_obj = tempfile.TemporaryDirectory()
        self.root = Path(self.td_obj.name)
        (self.root / "transitions").mkdir()
        (self.root / "evidence").mkdir()
        (self.root / "state").mkdir()
        (self.root / "inbox" / "m").mkdir(parents=True)
        (self.root / "inbox" / "other").mkdir(parents=True)

        self.keys_dir = self.root / "_keys"
        self.keys_dir.mkdir()
        self.m_priv, self.m_pub = _gen_ed25519_keypair(self.keys_dir, "m")
        self.o_priv, self.o_pub = _gen_ed25519_keypair(self.keys_dir, "other")

        self.ev1 = self.root / "evidence" / "e1.txt"
        self.ev1.write_text("evidence payload v1\n", encoding="utf-8")
        self.ev1_sha = hashlib.sha256(self.ev1.read_bytes()).hexdigest()

        self.ev2 = self.root / "evidence" / "e2.txt"
        self.ev2.write_text("evidence payload v2\n", encoding="utf-8")
        self.ev2_sha = hashlib.sha256(self.ev2.read_bytes()).hexdigest()

        _write_registry(
            self.root / "agents.yaml",
            [
                _make_agent_entry(agent_id="m", github_user="billgaohub", key_id="m-2026-01", pub_pem=self.m_pub),
                _make_agent_entry(agent_id="other", github_user="partner", key_id="other-2026-01", pub_pem=self.o_pub),
            ],
        )

    def tearDown(self) -> None:
        self.td_obj.cleanup()

    def _create_signed_v1_v2(self) -> tuple[Path, Path]:
        t1_path = self.root / "transitions" / "t1.json"
        t1 = _make_transition(
            tid="t-001",
            agent="m",
            key_id="m-2026-01",
            state_key="pilot/topic-1",
            state_value="accepted-v1",
            version=1,
            evidence_locator="evidence/e1.txt",
            evidence_sha256=self.ev1_sha,
        )
        t1_path.write_text(json.dumps(t1), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t1_path).returncode, 0)

        t2_path = self.root / "transitions" / "t2.json"
        t2 = _make_transition(
            tid="t-002",
            agent="other",
            key_id="other-2026-01",
            state_key="pilot/topic-1",
            state_value="accepted-v2",
            version=2,
            supersedes="t-001",
            verdict="VERIFIED_NO_CHANGE",
            evidence_locator="evidence/e2.txt",
            evidence_sha256=self.ev2_sha,
        )
        t2_path.write_text(json.dumps(t2), encoding="utf-8")
        self.assertEqual(_sign_file(self.o_priv, t2_path).returncode, 0)
        return t1_path, t2_path

    def test_positive_chain_projection_and_inconclusive(self) -> None:
        _t1, t2 = self._create_signed_v1_v2()
        res = _verify_cli(["--all", "--as-of", "2026-11-24"], self.root)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

        # Adding INCONCLUSIVE v3 supersedes t-002 must NOT overwrite v2 active state
        t3_path = self.root / "transitions" / "t3.json"
        t3 = _make_transition(
            tid="t-003",
            agent="m",
            key_id="m-2026-01",
            state_key="pilot/topic-1",
            state_value="inconclusive-v3",
            version=3,
            supersedes="t-002",
            verdict="INCONCLUSIVE",
            evidence_locator="evidence/e2.txt",
            evidence_sha256=self.ev2_sha,
        )
        t3_path.write_text(json.dumps(t3), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t3_path).returncode, 0)

        self.assertEqual(_verify_cli(["--as-of", "2026-11-24", str(t3_path)], self.root).returncode, 0)
        self.assertEqual(_render_cli([], self.root).returncode, 0)
        state_md = (self.root / "state" / "STATE.md").read_text(encoding="utf-8")
        self.assertIn("accepted-v2", state_md)
        self.assertIn("t-002", state_md)
        self.assertNotIn("inconclusive-v3", state_md)
        self.assertEqual(_render_cli(["--check"], self.root).returncode, 0)
        self.assertEqual(t2.name, "t2.json")

    def test_positive_github_blob_evidence_and_negative_invalid_blob(self) -> None:
        t_path = self.root / "transitions" / "t_blob.json"
        blob_sha = "a" * 40
        blob_url = f"https://github.com/billgaohub/agent-commons/blob/{'b' * 40}/README.md"
        t_blob = _make_transition(
            tid="t-blob-1",
            agent="m",
            key_id="m-2026-01",
            state_key="pilot/blob-test",
            state_value="ok",
            version=1,
        )
        t_blob["evidence"] = [
            {
                "type": "github-blob",
                "commit": "b" * 40,
                "locator": blob_url,
                "sha256": blob_sha,
                "observed_at": "2026-11-24T12:00:00+08:00",
            }
        ]
        t_blob["receipt"]["evidence_refs"] = [blob_url]
        t_path.write_text(json.dumps(t_blob), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t_path).returncode, 0)
        res_ok = _verify_cli(["--as-of", "2026-11-24", str(t_path)], self.root)
        self.assertEqual(res_ok.returncode, 0, res_ok.stdout)

        # Invalid github-blob URL should fail
        t_blob["evidence"][0]["locator"] = "https://example.com/not-github"
        t_blob["receipt"]["evidence_refs"] = ["https://example.com/not-github"]
        t_path.write_text(json.dumps(t_blob), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t_path).returncode, 0)
        res_bad = _verify_cli(["--as-of", "2026-11-24", str(t_path)], self.root)
        self.assertEqual(res_bad.returncode, 1)
        self.assertIn("GitHub blob URL", res_bad.stdout)

    def test_historical_revoked_key_passes_all_when_not_new(self) -> None:
        t1_path, _t2 = self._create_signed_v1_v2()
        _write_registry(
            self.root / "agents.yaml",
            [
                _make_agent_entry(
                    agent_id="m",
                    github_user="billgaohub",
                    key_id="m-2026-01",
                    pub_pem=self.m_pub,
                    status="revoked",
                ),
                _make_agent_entry(agent_id="other", github_user="partner", key_id="other-2026-01", pub_pem=self.o_pub),
            ],
        )
        # Historical verification succeeds
        res_hist = _verify_cli(["--all", "--as-of", "2026-11-24"], self.root)
        self.assertEqual(res_hist.returncode, 0, res_hist.stdout)
        # But treating t1 as new fails because key is revoked
        res_new = _verify_cli(["--all", "--new-files", str(t1_path), "--as-of", "2026-11-24"], self.root)
        self.assertEqual(res_new.returncode, 1)
        self.assertIn("revoked", res_new.stdout)

    def test_negative_tampered_payload(self) -> None:
        t1_path, _ = self._create_signed_v1_v2()
        data = json.loads(t1_path.read_text(encoding="utf-8"))
        data["state"]["value"] = "tampered"
        t1_path.write_text(json.dumps(data), encoding="utf-8")
        res = _verify_cli(["--as-of", "2026-11-24", str(t1_path)], self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("验签未通过", res.stdout)

    def test_negative_expired_key(self) -> None:
        _write_registry(
            self.root / "agents.yaml",
            [
                _make_agent_entry(
                    agent_id="m",
                    github_user="billgaohub",
                    key_id="m-2026-01",
                    pub_pem=self.m_pub,
                    expires="2020-01-01",
                )
            ],
        )
        t1_path = self.root / "transitions" / "t1.json"
        t1 = _make_transition(
            tid="t-exp",
            agent="m",
            key_id="m-2026-01",
            state_key="pilot/topic-1",
            state_value="v1",
            version=1,
            evidence_locator="evidence/e1.txt",
            evidence_sha256=self.ev1_sha,
        )
        t1_path.write_text(json.dumps(t1), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t1_path).returncode, 0)
        res = _verify_cli(["--as-of", "2026-11-24", str(t1_path)], self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("有效期", res.stdout)

    def test_negative_pending_key(self) -> None:
        _write_registry(
            self.root / "agents.yaml",
            [
                _make_agent_entry(
                    agent_id="m",
                    github_user="billgaohub",
                    key_id="m-2026-01",
                    pub_pem=self.m_pub,
                    status="pending",
                )
            ],
        )
        t1_path = self.root / "transitions" / "t1.json"
        t1 = _make_transition(
            tid="t-pend",
            agent="m",
            key_id="m-2026-01",
            state_key="pilot/topic-1",
            state_value="v1",
            version=1,
            evidence_locator="evidence/e1.txt",
            evidence_sha256=self.ev1_sha,
        )
        t1_path.write_text(json.dumps(t1), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t1_path).returncode, 0)
        res = _verify_cli(["--as-of", "2026-11-24", str(t1_path)], self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("pending", res.stdout)

    def test_negative_missing_scope_and_state_keys(self) -> None:
        _write_registry(
            self.root / "agents.yaml",
            [
                _make_agent_entry(
                    agent_id="m",
                    github_user="billgaohub",
                    key_id="m-2026-01",
                    pub_pem=self.m_pub,
                    scope=["inbox/m/"],
                )
            ],
        )
        t1_path = self.root / "transitions" / "t1.json"
        t1 = _make_transition(
            tid="t-scope",
            agent="m",
            key_id="m-2026-01",
            state_key="pilot/topic-1",
            state_value="v1",
            version=1,
            evidence_locator="evidence/e1.txt",
            evidence_sha256=self.ev1_sha,
        )
        t1_path.write_text(json.dumps(t1), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t1_path).returncode, 0)
        res = _verify_cli(["--as-of", "2026-11-24", str(t1_path)], self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("transitions/", res.stdout)

        # Also verify state_keys restriction
        _write_registry(
            self.root / "agents.yaml",
            [
                _make_agent_entry(
                    agent_id="m",
                    github_user="billgaohub",
                    key_id="m-2026-01",
                    pub_pem=self.m_pub,
                    state_keys=["pilot/allowed-only"],
                )
            ],
        )
        res2 = _verify_cli(["--as-of", "2026-11-24", str(t1_path)], self.root)
        self.assertEqual(res2.returncode, 1)
        self.assertIn("无权修改 state key", res2.stdout)

    def test_negative_evidence_failures(self) -> None:
        t1_path = self.root / "transitions" / "t1.json"

        # 1. Empty evidence
        t_empty = _make_transition(
            tid="t-ev0",
            agent="m",
            key_id="m-2026-01",
            state_key="pilot/topic-1",
            state_value="v1",
            version=1,
            evidence_locator="evidence/e1.txt",
            evidence_sha256=self.ev1_sha,
        )
        t_empty["evidence"] = []
        t1_path.write_text(json.dumps(t_empty), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t1_path).returncode, 0)
        res0 = _verify_cli(["--as-of", "2026-11-24", str(t1_path)], self.root)
        self.assertEqual(res0.returncode, 1)
        self.assertIn("evidence", res0.stdout)

        # 2. Wrong sha256
        t_badsha = _make_transition(
            tid="t-ev1",
            agent="m",
            key_id="m-2026-01",
            state_key="pilot/topic-1",
            state_value="v1",
            version=1,
            evidence_locator="evidence/e1.txt",
            evidence_sha256="0" * 64,
        )
        t1_path.write_text(json.dumps(t_badsha), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t1_path).returncode, 0)
        res1 = _verify_cli(["--as-of", "2026-11-24", str(t1_path)], self.root)
        self.assertEqual(res1.returncode, 1)
        self.assertIn("sha256 不匹配", res1.stdout)

        # 3. Path traversal
        (self.root / "outside.txt").write_text("secret\n", encoding="utf-8")
        t_trav = _make_transition(
            tid="t-ev2",
            agent="m",
            key_id="m-2026-01",
            state_key="pilot/topic-1",
            state_value="v1",
            version=1,
            evidence_locator="../outside.txt",
            evidence_sha256=hashlib.sha256(b"secret\n").hexdigest(),
        )
        t1_path.write_text(json.dumps(t_trav), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t1_path).returncode, 0)
        res2 = _verify_cli(["--as-of", "2026-11-24", str(t1_path)], self.root)
        self.assertEqual(res2.returncode, 1)
        self.assertIn("穿越", res2.stdout)

    def test_negative_chain_fake_supersedes_skipped_version_and_fork(self) -> None:
        t1_path, _t2 = self._create_signed_v1_v2()

        # Fake supersedes & skipped version
        t_bad_path = self.root / "transitions" / "t3.json"
        t_bad = _make_transition(
            tid="t-jump",
            agent="m",
            key_id="m-2026-01",
            state_key="pilot/topic-1",
            state_value="v99",
            version=99,
            supersedes="non-existent-id",
            evidence_locator="evidence/e1.txt",
            evidence_sha256=self.ev1_sha,
        )
        t_bad_path.write_text(json.dumps(t_bad), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t_bad_path).returncode, 0)
        res = _verify_cli(["--as-of", "2026-11-24", str(t_bad_path)], self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("不存在", res.stdout)

        # Forking supersedes (another transition superseding t-001)
        t_bad_path.unlink()
        t_fork_path = self.root / "transitions" / "t2b.json"
        t_fork = _make_transition(
            tid="t-fork",
            agent="m",
            key_id="m-2026-01",
            state_key="pilot/other-key",
            state_value="fork",
            version=2,
            supersedes="t-001",
            evidence_locator="evidence/e1.txt",
            evidence_sha256=self.ev1_sha,
        )
        t_fork_path.write_text(json.dumps(t_fork), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t_fork_path).returncode, 0)
        res2 = _verify_cli(["--as-of", "2026-11-24", str(t_fork_path)], self.root)
        self.assertEqual(res2.returncode, 1)
        self.assertIn("分叉", res2.stdout)
        self.assertEqual(t1_path.name, "t1.json")

    def test_negative_pr_author_mismatch(self) -> None:
        t1_path, _ = self._create_signed_v1_v2()
        res = _verify_cli(
            ["--pr-author", "partner", "--as-of", "2026-11-24", str(t1_path)],
            self.root,
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("PR 作者", res.stdout)


class CIGateGitIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.td_obj = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.td_obj.name)
        self.origin = self.base_dir / "origin.git"
        self.work = self.base_dir / "work"
        self.keys_dir = self.base_dir / "_keys"
        self.keys_dir.mkdir()

        self.m_priv, self.m_pub = _gen_ed25519_keypair(self.keys_dir, "m")
        self.o_priv, self.o_pub = _gen_ed25519_keypair(self.keys_dir, "other")

        subprocess.run(["git", "init", "--bare", str(self.origin)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(self.origin), str(self.work)], check=True, capture_output=True)
        _git(self.work, ["config", "user.name", "Test Runner"])
        _git(self.work, ["config", "user.email", "test@example.com"])
        _git(self.work, ["checkout", "-b", "main"])

        (self.work / "transitions").mkdir()
        (self.work / "evidence").mkdir()
        (self.work / "state").mkdir()
        (self.work / "inbox").mkdir()
        (self.work / "scripts").mkdir()
        (self.work / ".github" / "workflows").mkdir(parents=True)

        (self.work / "transitions" / "_TEMPLATE.json").write_text("{}\n", encoding="utf-8")
        (self.work / "inbox" / "_TEMPLATE.md").write_text("---\nid: <uuid>\n---\n", encoding="utf-8")
        (self.work / "scripts" / "dummy.py").write_text("print('ok')\n", encoding="utf-8")
        (self.work / ".github" / "workflows" / "validate.yml").write_text("name: v\n", encoding="utf-8")

        _write_registry(
            self.work / "agents.yaml",
            [
                _make_agent_entry(agent_id="m", github_user="billgaohub", key_id="m-2026-01", pub_pem=self.m_pub),
                _make_agent_entry(agent_id="other", github_user="partner", key_id="other-2026-01", pub_pem=self.o_pub),
            ],
        )
        (self.work / "state" / "STATE.md").write_text(
            render_state_markdown(self.work / "transitions"), encoding="utf-8"
        )

        _git(self.work, ["add", "-A"])
        _git(self.work, ["commit", "-m", "base"])
        _git(self.work, ["push", "-u", "origin", "main"])

    def tearDown(self) -> None:
        self.td_obj.cleanup()

    def _new_branch(self, name: str) -> None:
        _git(self.work, ["checkout", "main"])
        _git(self.work, ["checkout", "-b", name])

    def _commit_all(self, msg: str = "pr change") -> None:
        _git(self.work, ["add", "-A"])
        _git(self.work, ["commit", "-m", msg])

    def test_valid_inbox_and_valid_transition_prs_pass(self) -> None:
        # PR 1: inbox 提问 (without evidence) + 证据 (with evidence & unquoted ISO time)
        self._new_branch("pr-inbox")
        (self.work / "inbox" / "other").mkdir(parents=True, exist_ok=True)
        (self.work / "inbox" / "other" / "2026-11-24-q1.md").write_text(
            "---\nid: msg-1\nfrom: other\nto: m\ntime: 2026-11-24T12:00:00+08:00\ntype: 提问\n---\nQuestion?\n",
            encoding="utf-8",
        )
        (self.work / "inbox" / "other" / "2026-11-24-e1.md").write_text(
            "---\nid: msg-2\nfrom: other\nto: m\ntime: '2026-11-24T12:05:00+08:00'\ntype: 证据\nevidence:\n  - evidence/e1.txt\n---\nProof.\n",
            encoding="utf-8",
        )
        self._commit_all("inbox messages")
        res_in = _ci_cli(
            ["--event", "pull_request", "--base-ref", "main", "--pr-author", "partner", "--as-of", "2026-11-24"],
            self.work,
        )
        self.assertEqual(res_in.returncode, 0, res_in.stdout + res_in.stderr)

        # PR 2: evidence + signed transition + deterministic STATE.md
        self._new_branch("pr-transition")
        ev = self.work / "evidence" / "e1.txt"
        ev.write_text("real proof\n", encoding="utf-8")
        ev_sha = hashlib.sha256(ev.read_bytes()).hexdigest()
        t1_path = self.work / "transitions" / "t1.json"
        t1 = _make_transition(
            tid="t-ci-1",
            agent="other",
            key_id="other-2026-01",
            state_key="pilot/topic-1",
            state_value="done",
            version=1,
            evidence_locator="evidence/e1.txt",
            evidence_sha256=ev_sha,
        )
        t1_path.write_text(json.dumps(t1), encoding="utf-8")
        self.assertEqual(_sign_file(self.o_priv, t1_path).returncode, 0)
        (self.work / "state" / "STATE.md").write_text(
            render_state_markdown(self.work / "transitions"), encoding="utf-8"
        )
        self._commit_all("valid transition")
        res_tr = _ci_cli(
            ["--event", "pull_request", "--base-ref", "main", "--pr-author", "partner", "--as-of", "2026-11-24"],
            self.work,
        )
        self.assertEqual(res_tr.returncode, 0, res_tr.stdout + res_tr.stderr)

        # Simulate merge to main & push check
        _git(self.work, ["checkout", "main"])
        _git(self.work, ["merge", "--no-ff", "pr-transition", "-m", "merge t1"])
        _git(self.work, ["push", "origin", "main"])
        res_push = _ci_cli(["--event", "push", "--as-of", "2026-11-24"], self.work)
        self.assertEqual(res_push.returncode, 0, res_push.stdout + res_push.stderr)

    def test_attack_non_owner_tampering_agents_yaml_and_scripts(self) -> None:
        # Attack 1: partner tries to add evil key in agents.yaml and sign with it in same PR
        self._new_branch("atk-agents")
        evil_priv, evil_pub = _gen_ed25519_keypair(self.keys_dir, "evil")
        _write_registry(
            self.work / "agents.yaml",
            [
                _make_agent_entry(agent_id="m", github_user="billgaohub", key_id="m-2026-01", pub_pem=self.m_pub),
                _make_agent_entry(agent_id="other", github_user="partner", key_id="other-2026-01", pub_pem=evil_pub),
            ],
        )
        self._commit_all("tamper agents")
        res = _ci_cli(
            ["--event", "pull_request", "--base-ref", "main", "--pr-author", "partner", "--as-of", "2026-11-24"],
            self.work,
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("无权修改受保护治理文件", res.stdout)
        self.assertTrue(evil_priv.exists())

        # Attack 2: partner touches scripts/ or .github/
        self._new_branch("atk-scripts")
        (self.work / "scripts" / "dummy.py").write_text("print('pwned')\n", encoding="utf-8")
        self._commit_all("tamper scripts")
        res2 = _ci_cli(
            ["--event", "pull_request", "--base-ref", "main", "--pr-author", "partner", "--as-of", "2026-11-24"],
            self.work,
        )
        self.assertEqual(res2.returncode, 1)
        self.assertIn("无权修改受保护治理文件", res2.stdout)

    def test_attack_modify_or_delete_historical_transition(self) -> None:
        # Commit t1 to main first
        self._new_branch("seed-t1")
        ev = self.work / "evidence" / "e1.txt"
        ev.write_text("proof\n", encoding="utf-8")
        ev_sha = hashlib.sha256(ev.read_bytes()).hexdigest()
        t1_path = self.work / "transitions" / "t1.json"
        t1 = _make_transition(
            tid="t-hist-1",
            agent="m",
            key_id="m-2026-01",
            state_key="pilot/topic-1",
            state_value="v1",
            version=1,
            evidence_locator="evidence/e1.txt",
            evidence_sha256=ev_sha,
        )
        t1_path.write_text(json.dumps(t1), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t1_path).returncode, 0)
        (self.work / "state" / "STATE.md").write_text(
            render_state_markdown(self.work / "transitions"), encoding="utf-8"
        )
        self._commit_all("seed t1")
        _git(self.work, ["checkout", "main"])
        _git(self.work, ["merge", "--no-ff", "seed-t1"])
        _git(self.work, ["push", "origin", "main"])

        # Attack: delete historical transition
        self._new_branch("atk-del")
        t1_path.unlink()
        self._commit_all("delete t1")
        res_del = _ci_cli(
            ["--event", "pull_request", "--base-ref", "main", "--pr-author", "billgaohub", "--as-of", "2026-11-24"],
            self.work,
        )
        self.assertEqual(res_del.returncode, 1)
        self.assertIn("append-only", res_del.stdout)

        # Attack: modify historical transition (even re-signed!)
        self._new_branch("atk-mod")
        t1_mod = json.loads(t1_path.read_text(encoding="utf-8"))
        t1_mod["claim"]["statement"] = "rewritten history"
        t1_path.write_text(json.dumps(t1_mod), encoding="utf-8")
        self.assertEqual(_sign_file(self.m_priv, t1_path).returncode, 0)
        self._commit_all("modify t1")
        res_mod = _ci_cli(
            ["--event", "pull_request", "--base-ref", "main", "--pr-author", "billgaohub", "--as-of", "2026-11-24"],
            self.work,
        )
        self.assertEqual(res_mod.returncode, 1)
        self.assertIn("append-only", res_mod.stdout)

    def test_attack_manual_state_edit_and_template_bypass(self) -> None:
        # Attack 1: manual STATE.md edit alone
        self._new_branch("atk-state-only")
        (self.work / "state" / "STATE.md").write_text("# forged\n", encoding="utf-8")
        self._commit_all("forge state")
        res1 = _ci_cli(
            ["--event", "pull_request", "--base-ref", "main", "--pr-author", "billgaohub", "--as-of", "2026-11-24"],
            self.work,
        )
        self.assertEqual(res1.returncode, 1)
        self.assertIn("禁止手工编辑", res1.stdout)

        # Attack 2: edit _TEMPLATE.json + STATE.md
        self._new_branch("atk-template-bypass")
        (self.work / "transitions" / "_TEMPLATE.json").write_text('{"x":1}\n', encoding="utf-8")
        (self.work / "state" / "STATE.md").write_text("# forged via template\n", encoding="utf-8")
        self._commit_all("forge via template")
        res2 = _ci_cli(
            ["--event", "pull_request", "--base-ref", "main", "--pr-author", "billgaohub", "--as-of", "2026-11-24"],
            self.work,
        )
        self.assertEqual(res2.returncode, 1)
        self.assertIn("禁止手工编辑", res2.stdout)

        # Attack 3: valid transition + unrelated forged row in STATE.md
        self._new_branch("atk-piggyback-state")
        ev = self.work / "evidence" / "e1.txt"
        ev.write_text("proof\n", encoding="utf-8")
        ev_sha = hashlib.sha256(ev.read_bytes()).hexdigest()
        t1_path = self.work / "transitions" / "t1.json"
        t1 = _make_transition(
            tid="t-piggy-1",
            agent="other",
            key_id="other-2026-01",
            state_key="pilot/topic-1",
            state_value="v1",
            version=1,
            evidence_locator="evidence/e1.txt",
            evidence_sha256=ev_sha,
        )
        t1_path.write_text(json.dumps(t1), encoding="utf-8")
        self.assertEqual(_sign_file(self.o_priv, t1_path).returncode, 0)
        valid_md = render_state_markdown(self.work / "transitions")
        (self.work / "state" / "STATE.md").write_text(valid_md + "| rogue | x | 1 | VERIFIED_CHANGE | fake | other | now |\n", encoding="utf-8")
        self._commit_all("piggyback state")
        res3 = _ci_cli(
            ["--event", "pull_request", "--base-ref", "main", "--pr-author", "partner", "--as-of", "2026-11-24"],
            self.work,
        )
        self.assertEqual(res3.returncode, 1)
        self.assertIn("禁止手工编辑", res3.stdout)

    def test_attack_inbox_cross_agent_and_unverified_evidence_claim(self) -> None:
        # Attack 1: partner writes inside inbox/m/
        self._new_branch("atk-inbox-cross")
        (self.work / "inbox" / "m").mkdir(parents=True, exist_ok=True)
        (self.work / "inbox" / "m" / "2026-11-24-spoof.md").write_text(
            "---\nid: msg-spoof\nfrom: m\nto: other\ntime: 2026-11-24T12:00:00+08:00\ntype: 提问\n---\nhi\n",
            encoding="utf-8",
        )
        self._commit_all("cross inbox")
        res1 = _ci_cli(
            ["--event", "pull_request", "--base-ref", "main", "--pr-author", "partner", "--as-of", "2026-11-24"],
            self.work,
        )
        self.assertEqual(res1.returncode, 1)
        self.assertIn("inbox 越权", res1.stdout)

        # Attack 2: partner submits type: 证据 with empty/placeholder evidence (PILOT Test 3)
        self._new_branch("atk-inbox-no-evidence")
        (self.work / "inbox" / "other").mkdir(parents=True, exist_ok=True)
        (self.work / "inbox" / "other" / "2026-11-24-unsourced.md").write_text(
            "---\nid: msg-bad-ev\nfrom: other\nto: m\ntime: 2026-11-24T12:00:00+08:00\ntype: 证据\nevidence:\n  - <请填证据>\n---\n我断言某事实成立。\n",
            encoding="utf-8",
        )
        self._commit_all("unsourced evidence claim")
        res2 = _ci_cli(
            ["--event", "pull_request", "--base-ref", "main", "--pr-author", "partner", "--as-of", "2026-11-24"],
            self.work,
        )
        self.assertEqual(res2.returncode, 1)
        self.assertIn("禁止无来源断言", res2.stdout)

    def test_registry_multi_key_same_user_allowed_and_cross_user_rejected(self) -> None:
        _, m2_pub = _gen_ed25519_keypair(self.keys_dir, "m2")
        _write_registry(
            self.work / "agents.yaml",
            [
                _make_agent_entry(agent_id="m", github_user="billgaohub", key_id="m-2026-01", pub_pem=self.m_pub),
                _make_agent_entry(agent_id="m", github_user="billgaohub", key_id="m-2026-02", pub_pem=m2_pub),
                _make_agent_entry(agent_id="other", github_user="partner", key_id="other-2026-01", pub_pem=self.o_pub),
            ],
        )
        res_ok = _ci_cli(["--event", "push", "--as-of", "2026-11-24"], self.work)
        self.assertEqual(res_ok.returncode, 0, res_ok.stdout + res_ok.stderr)

        # Cross-user hijacking of same active agent_id must be rejected
        _write_registry(
            self.work / "agents.yaml",
            [
                _make_agent_entry(agent_id="m", github_user="billgaohub", key_id="m-2026-01", pub_pem=self.m_pub),
                _make_agent_entry(agent_id="m", github_user="intruder", key_id="m-2026-02", pub_pem=m2_pub),
            ],
        )
        res_bad = _ci_cli(["--event", "push", "--as-of", "2026-11-24"], self.work)
        self.assertEqual(res_bad.returncode, 1)
        self.assertIn("绑定了不同的 github_user", res_bad.stdout)


if __name__ == "__main__":
    unittest.main()
