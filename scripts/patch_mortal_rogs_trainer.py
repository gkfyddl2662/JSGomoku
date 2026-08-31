from __future__ import annotations

import argparse
import shutil
from pathlib import Path


IMPORT_ANCHOR = (
    "    from libriichi.consts import obs_shape\n"
    "    from config import config\n"
)
IMPORT_REPLACEMENT = (
    "    from libriichi.consts import obs_shape\n"
    "    from config import config\n"
    "    from training.mortal_hook import compute_mortal_rogs_batch, is_rogs_enabled\n"
)

STATS_ANCHOR = '''    stats = {
        'dqn_loss': 0,
        'cql_loss': 0,
        'next_rank_loss': 0,
    }
'''
STATS_REPLACEMENT_V1 = '''    stats = {
        'dqn_loss': 0,
        'cql_loss': 0,
        'next_rank_loss': 0,
        'rogs_loss': 0,
        'rogs_value_loss': 0,
        'rogs_regret_loss': 0,
    }
'''
STATS_REPLACEMENT = '''    stats = {
        'dqn_loss': 0,
        'cql_loss': 0,
        'next_rank_loss': 0,
        'rogs_loss': 0,
        'rogs_value_loss': 0,
        'rogs_regret_loss': 0,
        'rogs_bc_loss': 0,
        'rogs_cql_component': 0,
        'rogs_entropy': 0,
        'rogs_oracle_loss': 0,
        'rogs_search_loss': 0,
        'rogs_value_weighted': 0,
        'rogs_regret_weighted': 0,
        'rogs_bc_weighted': 0,
        'rogs_cql_weighted': 0,
        'rogs_entropy_weighted': 0,
        'rogs_oracle_weighted': 0,
        'rogs_search_weighted': 0,
        'rogs_value_weight': 0,
        'rogs_regret_weight': 0,
        'rogs_bc_weight': 0,
        'rogs_cql_weight': 0,
        'rogs_entropy_weight': 0,
        'rogs_oracle_weight': 0,
        'rogs_search_weight': 0,
        'rogs_regret_target_mean': 0,
        'rogs_regret_target_sq_mean': 0,
        'rogs_regret_clip_fraction': 0,
        'rogs_legal_action_count': 0,
        'rogs_oracle_available': 0,
        'rogs_search_available': 0,
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
LOSS_ANCHOR_RTX = LOSS_ANCHOR.replace(
    "with torch.autocast(device.type, enabled=enable_amp):",
    "with torch.autocast(device.type, dtype=amp_dtype if device.type == 'cuda' else None, enabled=enable_amp):",
)
LOSS_REPLACEMENT_TEMPLATE = '''{autocast}
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
STATS_UPDATE_V1 = '''                stats['dqn_loss'] += dqn_loss
                if not online:
                    stats['cql_loss'] += cql_loss
                stats['next_rank_loss'] += next_rank_loss
                if rogs_batch is not None:
                    stats['rogs_loss'] += rogs_batch.objective.total.detach()
                    stats['rogs_value_loss'] += rogs_batch.objective.components['value'].detach()
                    stats['rogs_regret_loss'] += rogs_batch.objective.components['regret'].detach()
                all_q[idx] = q
'''
STATS_UPDATE_REPLACEMENT = '''                stats['dqn_loss'] += dqn_loss
                if not online:
                    stats['cql_loss'] += cql_loss
                stats['next_rank_loss'] += next_rank_loss
                if rogs_batch is not None:
                    components = rogs_batch.objective.components
                    weights = rogs_batch.objective.weights
                    zero = rogs_batch.objective.total.detach() * 0
                    value_component = components['value'].detach()
                    regret_component = components['regret'].detach()
                    bc_component = components.get('behavior_cloning', zero).detach()
                    cql_component = components.get('cql', zero).detach()
                    entropy_component = components['entropy'].detach()
                    oracle_component = components.get('oracle', zero).detach()
                    search_component = components.get('search', zero).detach()
                    stats['rogs_loss'] += rogs_batch.objective.total.detach()
                    stats['rogs_value_loss'] += value_component
                    stats['rogs_regret_loss'] += regret_component
                    stats['rogs_bc_loss'] += bc_component
                    stats['rogs_cql_component'] += cql_component
                    stats['rogs_entropy'] += entropy_component
                    stats['rogs_oracle_loss'] += oracle_component
                    stats['rogs_search_loss'] += search_component
                    stats['rogs_value_weighted'] += value_component * weights.value
                    stats['rogs_regret_weighted'] += regret_component * weights.regret
                    stats['rogs_bc_weighted'] += bc_component * weights.behavior_cloning
                    stats['rogs_cql_weighted'] += cql_component * weights.cql
                    stats['rogs_entropy_weighted'] += entropy_component * weights.entropy
                    stats['rogs_oracle_weighted'] += oracle_component * weights.oracle
                    stats['rogs_search_weighted'] += search_component * weights.search
                    stats['rogs_value_weight'] += weights.value
                    stats['rogs_regret_weight'] += weights.regret
                    stats['rogs_bc_weight'] += weights.behavior_cloning
                    stats['rogs_cql_weight'] += weights.cql
                    stats['rogs_entropy_weight'] += weights.entropy
                    stats['rogs_oracle_weight'] += weights.oracle
                    stats['rogs_search_weight'] += weights.search
                    raw_target = rogs_batch.regret_target_raw.detach().float()
                    stats['rogs_regret_target_mean'] += raw_target.mean()
                    stats['rogs_regret_target_sq_mean'] += raw_target.square().mean()
                    regret_clip = float(config.get('objective', {}).get('regret_clip', 12.0))
                    stats['rogs_regret_clip_fraction'] += (raw_target.abs() > regret_clip).float().mean()
                    stats['rogs_legal_action_count'] += rogs_batch.legal_action_count.detach().float().mean()
                    stats['rogs_oracle_available'] += float(rogs_batch.oracle_available)
                    stats['rogs_search_available'] += float(rogs_batch.search_available)
                all_q[idx] = q
'''

TB_ANCHOR = '''                writer.add_scalar('loss/next_rank_loss', stats['next_rank_loss'] / save_every, steps)
                writer.add_scalar('hparam/lr', scheduler.get_last_lr()[0], steps)
'''
TB_REPLACEMENT_V1 = '''                writer.add_scalar('loss/next_rank_loss', stats['next_rank_loss'] / save_every, steps)
                if is_rogs_enabled(config, version):
                    writer.add_scalar('loss/rogs_total', stats['rogs_loss'] / save_every, steps)
                    writer.add_scalar('loss/rogs_value', stats['rogs_value_loss'] / save_every, steps)
                    writer.add_scalar('loss/rogs_regret', stats['rogs_regret_loss'] / save_every, steps)
                writer.add_scalar('hparam/lr', scheduler.get_last_lr()[0], steps)
'''
TB_REPLACEMENT = '''                writer.add_scalar('loss/next_rank_loss', stats['next_rank_loss'] / save_every, steps)
                if is_rogs_enabled(config, version):
                    writer.add_scalar('loss/rogs_total', stats['rogs_loss'] / save_every, steps)
                    writer.add_scalar('loss/rogs_value', stats['rogs_value_loss'] / save_every, steps)
                    writer.add_scalar('loss/rogs_regret', stats['rogs_regret_loss'] / save_every, steps)
                    writer.add_scalar('loss/rogs_bc', stats['rogs_bc_loss'] / save_every, steps)
                    writer.add_scalar('loss/rogs_cql', stats['rogs_cql_component'] / save_every, steps)
                    writer.add_scalar('loss/rogs_entropy', stats['rogs_entropy'] / save_every, steps)
                    writer.add_scalar('loss/rogs_oracle', stats['rogs_oracle_loss'] / save_every, steps)
                    writer.add_scalar('loss/rogs_search', stats['rogs_search_loss'] / save_every, steps)
                    writer.add_scalar('loss_weighted/rogs_value', stats['rogs_value_weighted'] / save_every, steps)
                    writer.add_scalar('loss_weighted/rogs_regret', stats['rogs_regret_weighted'] / save_every, steps)
                    writer.add_scalar('loss_weighted/rogs_bc', stats['rogs_bc_weighted'] / save_every, steps)
                    writer.add_scalar('loss_weighted/rogs_cql', stats['rogs_cql_weighted'] / save_every, steps)
                    writer.add_scalar('loss_weighted/rogs_entropy', stats['rogs_entropy_weighted'] / save_every, steps)
                    writer.add_scalar('loss_weighted/rogs_oracle', stats['rogs_oracle_weighted'] / save_every, steps)
                    writer.add_scalar('loss_weighted/rogs_search', stats['rogs_search_weighted'] / save_every, steps)
                    writer.add_scalar('rogs_weight/value', stats['rogs_value_weight'] / save_every, steps)
                    writer.add_scalar('rogs_weight/regret', stats['rogs_regret_weight'] / save_every, steps)
                    writer.add_scalar('rogs_weight/bc', stats['rogs_bc_weight'] / save_every, steps)
                    writer.add_scalar('rogs_weight/cql', stats['rogs_cql_weight'] / save_every, steps)
                    writer.add_scalar('rogs_weight/entropy', stats['rogs_entropy_weight'] / save_every, steps)
                    writer.add_scalar('rogs_weight/oracle', stats['rogs_oracle_weight'] / save_every, steps)
                    writer.add_scalar('rogs_weight/search', stats['rogs_search_weight'] / save_every, steps)
                    regret_mean = stats['rogs_regret_target_mean'] / save_every
                    regret_sq_mean = stats['rogs_regret_target_sq_mean'] / save_every
                    regret_var = max(0.0, float(regret_sq_mean) - float(regret_mean) ** 2)
                    writer.add_scalar('rogs_diag/regret_target_mean', regret_mean, steps)
                    writer.add_scalar('rogs_diag/regret_target_std', regret_var ** 0.5, steps)
                    writer.add_scalar('rogs_diag/regret_clip_fraction', stats['rogs_regret_clip_fraction'] / save_every, steps)
                    writer.add_scalar('rogs_diag/legal_action_count', stats['rogs_legal_action_count'] / save_every, steps)
                    writer.add_scalar('rogs_diag/oracle_available', stats['rogs_oracle_available'] / save_every, steps)
                    writer.add_scalar('rogs_diag/search_available', stats['rogs_search_available'] / save_every, steps)
                writer.add_scalar('hparam/lr', scheduler.get_last_lr()[0], steps)
'''


def replace_once(text: str, anchor: str, replacement: str, label: str) -> str:
    if replacement in text:
        return text
    count = text.count(anchor)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(anchor, replacement, 1)


def replace_or_upgrade(text: str, stock: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{label}: expected one managed-v1 anchor")
        return text.replace(old, new, 1)
    return replace_once(text, stock, new, label)


def replace_loss(text: str) -> str:
    if "rogs_batch = compute_mortal_rogs_batch(" in text:
        return text
    if text.count(LOSS_ANCHOR_RTX) == 1:
        replacement = LOSS_REPLACEMENT_TEMPLATE.format(
            autocast="            with torch.autocast(device.type, dtype=amp_dtype if device.type == 'cuda' else None, enabled=enable_amp):"
        )
        return text.replace(LOSS_ANCHOR_RTX, replacement, 1)
    if text.count(LOSS_ANCHOR) == 1:
        replacement = LOSS_REPLACEMENT_TEMPLATE.format(
            autocast="            with torch.autocast(device.type, enabled=enable_amp):"
        )
        return text.replace(LOSS_ANCHOR, replacement, 1)
    raise RuntimeError("loss: expected exactly one stock or RTX-patched anchor")


def apply(train_py: Path) -> None:
    text = train_py.read_text(encoding="utf-8")
    backup = train_py.with_suffix(train_py.suffix + ".pre-rogs.bak")
    if not backup.exists():
        shutil.copy2(train_py, backup)

    text = replace_once(text, IMPORT_ANCHOR, IMPORT_REPLACEMENT, "import")
    text = replace_or_upgrade(text, STATS_ANCHOR, STATS_REPLACEMENT_V1, STATS_REPLACEMENT, "stats")
    text = replace_loss(text)
    text = replace_or_upgrade(
        text,
        STATS_UPDATE_ANCHOR,
        STATS_UPDATE_V1,
        STATS_UPDATE_REPLACEMENT,
        "stats update",
    )
    text = replace_or_upgrade(text, TB_ANCHOR, TB_REPLACEMENT_V1, TB_REPLACEMENT, "tensorboard")

    required = (
        "compute_mortal_rogs_batch",
        "is_rogs_enabled(config, version)",
        "loss/rogs_total",
        "loss/rogs_bc",
        "loss/rogs_cql",
        "loss_weighted/rogs_regret",
        "rogs_weight/cql",
        "rogs_diag/regret_target_std",
        "rogs_diag/oracle_available",
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
