from __future__ import annotations

import argparse
import py_compile
import shutil
import subprocess
from pathlib import Path


MODEL_SHA = "0fce8aaf19e3cbff2be3d9c241c53dad4e59ddce"
MARKER = "# MORTAL_ROGS_UNIFIED_MODEL_STAGE1"


def git_blob_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_model(text: str) -> str:
    if MARKER in text:
        return text

    text = replace_once(
        text,
        "from libriichi.consts import obs_shape, oracle_obs_shape, ACTION_SPACE, GRP_SIZE\n",
        "from libriichi.consts import obs_shape, oracle_obs_shape, ACTION_SPACE, GRP_SIZE\n\n"
        f"{MARKER}\n",
        "unified marker",
    )

    text = replace_once(
        text,
        "    def __init__(self, *, conv_channels, num_blocks, is_oracle=False, version=1):\n",
        "    def __init__(self, *, conv_channels, num_blocks, is_oracle=False, version=1, "
        "obs_channels=None, oracle_obs_channels=None):\n",
        "Brain signature",
    )
    text = replace_once(
        text,
        "        in_channels = obs_shape(version)[0]\n"
        "        if is_oracle:\n"
        "            in_channels += oracle_obs_shape(version)[0]\n",
        "        in_channels = obs_shape(version)[0] if obs_channels is None else int(obs_channels)\n"
        "        if is_oracle:\n"
        "            oracle_channels = (\n"
        "                oracle_obs_shape(version)[0]\n"
        "                if oracle_obs_channels is None\n"
        "                else int(oracle_obs_channels)\n"
        "            )\n"
        "            in_channels += oracle_channels\n",
        "Brain input channels",
    )

    text = replace_once(
        text,
        "class DQN(nn.Module):\n"
        "    def __init__(self, *, version=1):\n"
        "        super().__init__()\n"
        "        self.version = version\n",
        "class DQN(nn.Module):\n"
        "    def __init__(self, *, version=1, action_space=ACTION_SPACE):\n"
        "        super().__init__()\n"
        "        self.version = version\n"
        "        self.action_space = int(action_space)\n",
        "DQN signature",
    )

    dqn_start = text.index("class DQN(nn.Module):")
    grp_start = text.index("class GRP(nn.Module):", dqn_start)
    dqn = text[dqn_start:grp_start]
    dqn = dqn.replace("nn.Linear(512, ACTION_SPACE)", "nn.Linear(512, self.action_space)")
    dqn = dqn.replace("nn.Linear(hidden_size, ACTION_SPACE)", "nn.Linear(hidden_size, self.action_space)")
    dqn = dqn.replace("nn.Linear(1024, 1 + ACTION_SPACE)", "nn.Linear(1024, 1 + self.action_space)")
    dqn = dqn.replace(
        "v, a = self.net(phi).split((1, ACTION_SPACE), dim=-1)",
        "v, a = self.net(phi).split((1, self.action_space), dim=-1)",
    )
    text = text[:dqn_start] + dqn + text[grp_start:]

    # The DQN substitutions change source length, so locate GRP again before
    # replacing it. Reusing the old offset can splice `class GRP` into DQN.
    grp_start = text.index("class GRP(nn.Module):", dqn_start)
    grp = '''class GRP(nn.Module):
    def __init__(self, hidden_size=64, num_layers=2, num_players=4, input_size=None, dtype=torch.float64):
        super().__init__()
        if num_players not in (3, 4):
            raise ValueError(f'num_players must be 3 or 4, got {num_players}')
        self.num_players = int(num_players)
        if input_size is None:
            input_size = 3 + self.num_players
        num_perms = 6 if self.num_players == 3 else 24

        self.rnn = nn.GRU(
            input_size=int(input_size),
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_size * num_layers, hidden_size * num_layers),
            nn.ReLU(inplace=True),
            nn.Linear(hidden_size * num_layers, num_perms),
        )
        for mod in self.modules():
            mod.to(dtype=dtype)

        perms = torch.tensor(list(permutations(range(self.num_players))))
        perms_t = perms.transpose(0, 1)
        self.register_buffer('perms', perms)
        self.register_buffer('perms_t', perms_t)

    def forward(self, inputs: List[Tensor]):
        lengths = torch.tensor([t.shape[0] for t in inputs], dtype=torch.int64)
        inputs = pad_sequence(inputs, batch_first=True)
        packed_inputs = pack_padded_sequence(inputs, lengths, batch_first=True, enforce_sorted=False)
        return self.forward_packed(packed_inputs)

    def forward_packed(self, packed_inputs):
        _, state = self.rnn(packed_inputs)
        state = state.transpose(0, 1).flatten(1)
        logits = self.fc(state)
        return logits

    def calc_matrix(self, logits: Tensor):
        batch_size = logits.shape[0]
        n = self.num_players
        probs = logits.softmax(-1)
        matrix = torch.zeros(batch_size, n, n, dtype=probs.dtype, device=probs.device)
        for player in range(n):
            for rank in range(n):
                cond = self.perms_t[player] == rank
                matrix[:, player, rank] = probs[:, cond].sum(-1)
        return matrix

    def get_label(self, rank_by_player: Tensor):
        batch_size = rank_by_player.shape[0]
        perms = self.perms.expand(batch_size, -1, -1).transpose(0, 1)
        mappings = (perms == rank_by_player).all(-1).nonzero()

        labels = torch.zeros(batch_size, dtype=torch.int64, device=mappings.device)
        labels[mappings[:, 1]] = mappings[:, 0]
        return labels
'''
    return text[:grp_start] + grp


def apply(root: Path) -> None:
    model = root / "mortal" / "model.py"
    if not model.is_file():
        raise RuntimeError(f"stock Mortal model.py not found: {model}")

    original = model.read_text(encoding="utf-8")
    if MARKER not in original:
        actual = git_blob_sha(model)
        if actual != MODEL_SHA:
            raise RuntimeError(
                f"unexpected stock Mortal model.py: expected {MODEL_SHA}, got {actual}"
            )

    updated = patch_model(original)
    if updated != original:
        backup = model.with_suffix(".py.unified-stage1.bak")
        if not backup.exists():
            shutil.copy2(model, backup)
        model.write_text(updated, encoding="utf-8")
        print(f"patched: {model}")
    else:
        print(f"unchanged: {model}")

    post = model.read_text(encoding="utf-8")
    required = (
        MARKER,
        "action_space=ACTION_SPACE",
        "self.action_space = int(action_space)",
        "obs_channels=None",
        "num_players=4, input_size=None",
        "num_perms = 6 if self.num_players == 3 else 24",
    )
    missing = [needle for needle in required if needle not in post]
    if missing:
        raise RuntimeError(f"unified model Stage 1 postconditions failed: {missing}")

    py_compile.compile(str(model), doraise=True)
    print("MORTAL_UNIFIED_MODEL_STAGE1_OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    apply(args.root.expanduser().resolve())


if __name__ == "__main__":
    main()
