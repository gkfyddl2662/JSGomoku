from __future__ import annotations

import argparse
import shutil
from pathlib import Path


IMPORT_ANCHOR = "    from config import config\n"
IMPORT_REPLACEMENT = (
    "    from config import config\n"
    "    from training.mortal_hook import compute_mortal_rogs_batch, is_rogs_enabled\n"
)

STATS_ANCHOR = '''    stats = {
        'dqn_loss': 0,
        'cql_loss': 0,
        'next_rank_loss': 0,
    }
'''
STATS_REPLACEMENT = '''    stats = {
        'dqn_loss': 0,
        'cql_loss': 0,
        'next_rank_loss': 0,
        'rogs_loss': 0,
        'rogs_value_loss': 0,
        'rogs_regret_loss': 0,
    }
'''

LOSS_ANCHOR = '''            with torch.autocast(device.type, enabled=enable_amp):
                phi = mortal(obs)
                q_out = dqn(phi, masks)
                q = q_out[range(batch_size), actions]
                dqn_loss = 0.5 * mse(q, q_target_mc)
                cql_loss = 0
                if not online:
                    cql_loss = q_out.logsumexp(-1).mean() - q.mean()

                next_rank_logits, = aux_net(phi)
                next_rank_loss = ce(next_rank_logits, player_ranks)

                loss = sum((
                    dqn_loss,
                    cql_loss * min_q_weight,
                    next_rank_loss * next_rank_weight,
                ))
'''
LOSS_REPLACEMENT = '''            with torch.autocast(device.type, enabled=enable_amp):
                phi = mortal(obs)
                q_out = dqn(phi, masks)
                q = q_out[range(batch_size), actions]
                dqn_loss = 0.5 * mse(q, q_target_mc)
                cql_loss = 0
                if not online:
                    cql_loss = q_out.logsumexp(-1).mean() - q.mean()

                next_rank_logits, = aux_net(phi)
                next_rank_loss = ce(next_rank_logits, player_ranks)

                rogs_batch = None
                if is_rogs_enabled(config, version):
                    rogs_batch = compute_mortal_rogs_batch(
                        dqn=dqn,
                        phi=phi,
                        masks=masks,
                        actions=actions,
                        returns=q_target_mc,
                        cql_loss=None if online else cql_loss,
                        config=config,
                        steps=steps,
                        enable_behavior_cloning=not online,
                    )
                    q_out = rogs_batch.outputs.q
                    q = rogs_batch.chosen_q
                    loss = rogs_batch.objective.total + next_rank_loss * next_rank_weight
                else:
                    loss = sum((
                        dqn_loss,
                        cql_loss * min_q_weight,
                        next_rank_loss * next_rank_weight,
                    ))
'''

STATS_UPDATE_ANCHOR = '''                stats['dqn_loss'] += dqn_loss
                if not online:
                    stats['cql_loss'] += cql_loss
                stats['next_rank_loss'] += next_rank_loss
                all_q[idx] = q
'''
STATS_UPDATE_REPLACEMENT = '''                stats['dqn_loss'] += dqn_loss
                if not online:
                    stats['cql_loss'] += cql_loss
                stats['next_rank_loss'] += next_rank_loss
                if rogs_batch is not None:
                    stats['rogs_loss'] += rogs_batch.objective.total.detach()
                    stats['rogs_value_loss'] += rogs_batch.objective.components['value'].detach()
                    stats['rogs_regret_loss'] += rogs_batch.objective.components['regret'].detach()
                all_q[idx] = q
'''

TB_ANCHOR = '''                writer.add_scalar('loss/next_rank_loss', stats['next_rank_loss'] / save_every, steps)
                writer.add_scalar('hparam/lr', scheduler.get_last_lr()[0], steps)
'''
TB_REPLACEMENT = '''                writer.add_scalar('loss/next_rank_loss', stats['next_rank_loss'] / save_every, steps)
                if is_rogs_enabled(config, version):
                    writer.add_scalar('loss/rogs_total', stats['rogs_loss'] / save_every, steps)
                    writer.add_scalar('loss/rogs_value', stats['rogs_value_loss'] / save_every, steps)
                    writer.add_scalar('loss/rogs_regret', stats['rogs_regret_loss'] / save_every, steps)
                writer.add_scalar('hparam/lr', scheduler.get_last_lr()[0], steps)
'''


def replace_once(text: str, anchor: str, replacement: str, label: str) -> str:
    if replacement in text:
        return text
    count = text.count(anchor)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(anchor, replacement, 1)


def apply(train_py: Path) -> None:
    text = train_py.read_text(encoding="utf-8")
    backup = train_py.with_suffix(train_py.suffix + ".pre-rogs.bak")
    if not backup.exists():
        shutil.copy2(train_py, backup)

    text = replace_once(text, IMPORT_ANCHOR, IMPORT_REPLACEMENT, "import")
    text = replace_once(text, STATS_ANCHOR, STATS_REPLACEMENT, "stats")
    text = replace_once(text, LOSS_ANCHOR, LOSS_REPLACEMENT, "loss")
    text = replace_once(text, STATS_UPDATE_ANCHOR, STATS_UPDATE_REPLACEMENT, "stats update")
    text = replace_once(text, TB_ANCHOR, TB_REPLACEMENT, "tensorboard")

    required = (
        "compute_mortal_rogs_batch",
        "is_rogs_enabled(config, version)",
        "loss/rogs_total",
        "enable_behavior_cloning=not online",
    )
    for token in required:
        if token not in text:
            raise RuntimeError(f"ROGS trainer postcondition missing: {token}")
    train_py.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-py", type=Path, required=True)
    args = parser.parse_args()
    target = args.train_py.resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    apply(target)
    print(f"MORTAL_ROGS_TRAINER_OK {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
