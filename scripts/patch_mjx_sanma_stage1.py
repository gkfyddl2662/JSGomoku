from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


RULE_HEADER = r'''#ifndef MJX_INTERNAL_RULE_H
#define MJX_INTERNAL_RULE_H

#include <cstddef>
#include <cstdint>

namespace mjx::internal {

enum class GameMode : std::uint8_t { kYonma = 4, kSanma = 3 };

struct RuleConfig {
  GameMode mode = GameMode::kYonma;
  bool allow_chi = true;
  bool allow_nuki = false;
  bool nuki_is_dora = false;
  bool tsumo_loss = true;
  int starting_points = 25000;
  int return_points = 30000;
  int rounds_per_wind = 4;
  int dead_wall_tiles = 14;

  [[nodiscard]] constexpr bool IsSanma() const noexcept {
    return mode == GameMode::kSanma;
  }
  [[nodiscard]] constexpr int num_players() const noexcept {
    return IsSanma() ? 3 : 4;
  }
  [[nodiscard]] constexpr std::size_t wall_tiles() const noexcept {
    return IsSanma() ? 108u : 136u;
  }
  [[nodiscard]] constexpr int initial_tiles() const noexcept {
    return 13 * num_players();
  }

  static constexpr RuleConfig Yonma() noexcept { return RuleConfig{}; }

  static constexpr RuleConfig Sanma() noexcept {
    RuleConfig rule{};
    rule.mode = GameMode::kSanma;
    rule.allow_chi = false;
    rule.allow_nuki = true;
    rule.nuki_is_dora = true;
    rule.tsumo_loss = false;
    rule.starting_points = 35000;
    rule.return_points = 40000;
    rule.rounds_per_wind = 3;
    return rule;
  }

  static constexpr RuleConfig FromWallSize(std::size_t size) noexcept {
    return size == 108u ? Sanma() : Yonma();
  }
};

}  // namespace mjx::internal

#endif  // MJX_INTERNAL_RULE_H
'''

TILE_H_INCLUDE_ANCHOR = '#include "mjx/internal/types.h"\n#include "mjx/internal/utils.h"'
TILE_H_INCLUDE_REPLACEMENT = '#include "mjx/internal/rule.h"\n#include "mjx/internal/types.h"\n#include "mjx/internal/utils.h"'
TILE_H_DECL_ANCHOR = '  static std::vector<Tile> CreateAll() noexcept;  // tiles are sorted\n'
TILE_H_DECL_REPLACEMENT = (
    '  static std::vector<Tile> CreateAll() noexcept;  // default: yonma, sorted\n'
    '  static std::vector<Tile> CreateAll(const RuleConfig &rule) noexcept;\n'
)

TILE_CPP_ANCHOR = '''std::vector<Tile> Tile::CreateAll() noexcept {
  // TODO: switch depending on rule::PLAYER_NUM
  auto ids = std::vector<TileId>(136);
  std::iota(ids.begin(), ids.end(), 0);
  auto tiles = Tile::Create(ids);
  return tiles;
}
'''

TILE_CPP_REPLACEMENT = '''std::vector<Tile> Tile::CreateAll() noexcept {
  return CreateAll(RuleConfig::Yonma());
}

std::vector<Tile> Tile::CreateAll(const RuleConfig &rule) noexcept {
  std::vector<TileId> ids;
  ids.reserve(rule.wall_tiles());
  for (int raw_id = 0; raw_id < 136; ++raw_id) {
    const auto type = static_cast<TileType>(raw_id / 4);
    if (rule.IsSanma() && TileType::kM2 <= type && type <= TileType::kM8)
      continue;
    ids.emplace_back(static_cast<TileId>(raw_id));
  }
  Assert(ids.size() == rule.wall_tiles());
  return Tile::Create(ids);
}
'''


def replace_once(path: Path, anchor: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return
    count = text.count(anchor)
    if count != 1:
        raise RuntimeError(f"Expected exactly one patch anchor in {path}, found {count}")
    path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")


def git_blob_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def require_sha(path: Path, expected: str) -> None:
    actual = git_blob_sha(path)
    if actual != expected:
        raise RuntimeError(
            f"Refusing to patch unexpected upstream file {path}: expected {expected}, got {actual}"
        )


def apply(root: Path) -> None:
    tile_h = root / "include/mjx/internal/tile.h"
    tile_cpp = root / "include/mjx/internal/tile.cpp"
    rule_h = root / "include/mjx/internal/rule.h"

    already_patched = rule_h.exists() and "CreateAll(const RuleConfig &rule)" in tile_h.read_text(encoding="utf-8")
    if not already_patched:
        require_sha(tile_h, "d15f08309009af5d0a2e58d87725e68ff80cb103")
        require_sha(tile_cpp, "dffd5905fed2b32b036a1ec6b54600bf07b670e9")

    rule_h.write_text(RULE_HEADER, encoding="utf-8")
    replace_once(tile_h, TILE_H_INCLUDE_ANCHOR, TILE_H_INCLUDE_REPLACEMENT)
    replace_once(tile_h, TILE_H_DECL_ANCHOR, TILE_H_DECL_REPLACEMENT)
    replace_once(tile_cpp, TILE_CPP_ANCHOR, TILE_CPP_REPLACEMENT)

    if "TileType::kM2 <= type && type <= TileType::kM8" not in tile_cpp.read_text(encoding="utf-8"):
        raise RuntimeError("Sanma tile removal postcondition failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    apply(args.root.resolve())
    print("MJX_SANMA_STAGE1_OK rule + 108-tile sanma set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
