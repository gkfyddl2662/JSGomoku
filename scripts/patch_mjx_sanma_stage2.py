from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


WALL_H_CTOR_ANCHOR = '''  explicit Wall(std::uint64_t round, std::uint64_t honba,
                std::uint64_t game_seed);
'''
WALL_H_CTOR_REPLACEMENT = '''  explicit Wall(std::uint64_t round, std::uint64_t honba,
                std::uint64_t game_seed);
  Wall(std::uint64_t round, std::uint64_t honba, std::uint64_t game_seed,
       const RuleConfig& rule);
'''
WALL_H_PRIVATE_ANCHOR = '''  std::uint32_t round_;
  GameSeed game_seed_;
  std::vector<Tile> tiles_;
  int draw_ix_ = 52;
  int num_kan_draw_ = 0;
  int num_kan_dora_ = 0;
'''
WALL_H_PRIVATE_REPLACEMENT = '''  [[nodiscard]] int live_wall_end() const noexcept;
  [[nodiscard]] int dora_base_ix() const noexcept;

  std::uint32_t round_;
  GameSeed game_seed_;
  RuleConfig rule_ = RuleConfig::Yonma();
  std::vector<Tile> tiles_;
  int draw_ix_ = 0;
  int num_kan_draw_ = 0;
  int num_kan_dora_ = 0;
'''

CTOR_ANCHOR = '''Wall::Wall(std::uint64_t round, std::uint64_t honba, std::uint64_t game_seed)
    : round_(round), game_seed_(game_seed), tiles_(Tile::CreateAll()) {
  auto wall_seed = game_seed_.GetWallSeed(round, honba);
  // std::cout << "round: " << std::to_string(round) << ", honba: " <<
  // std::to_string(honba) << ", game_seed: " << std::to_string(seed) << ",
  // wall_seed: " << std::to_string(wall_seed) << std::endl;
  Shuffle(tiles_.begin(), tiles_.end(), std::mt19937_64(wall_seed));
}

Wall::Wall(std::uint32_t round, std::vector<Tile> tiles)
    : round_(round), game_seed_(-1), tiles_(std::move(tiles)) {}
'''
CTOR_REPLACEMENT = '''Wall::Wall(std::uint64_t round, std::uint64_t honba, std::uint64_t game_seed)
    : Wall(round, honba, game_seed, RuleConfig::Yonma()) {}

Wall::Wall(std::uint64_t round, std::uint64_t honba, std::uint64_t game_seed,
           const RuleConfig& rule)
    : round_(round),
      game_seed_(game_seed),
      rule_(rule),
      tiles_(Tile::CreateAll(rule)),
      draw_ix_(rule.initial_tiles()) {
  auto wall_seed = game_seed_.GetWallSeed(round, honba);
  Shuffle(tiles_.begin(), tiles_.end(), std::mt19937_64(wall_seed));
}

Wall::Wall(std::uint32_t round, std::vector<Tile> tiles)
    : round_(round),
      game_seed_(-1),
      rule_(RuleConfig::FromWallSize(tiles.size())),
      tiles_(std::move(tiles)),
      draw_ix_(rule_.initial_tiles()) {}
'''

INITIAL_HAND_ANCHOR = '''std::vector<Tile> Wall::initial_hand_tiles(AbsolutePos pos) const {
  auto pos_ix = ToUType(pos);
  auto ix = ((pos_ix % 4 - round_ % 4 + 4) % 4) * 4;
  std::vector<Tile> tiles;
  tiles.reserve(13);
  for (int i = 0; i < 3; ++i) {
    for (int j = 0; j < 4; ++j) {
      tiles.emplace_back(tiles_.at(ix++));
    }
    ix += 12;
  }
  ix = (pos_ix % 4 - round_ % 4 + 4) % 4 + 48;
  tiles.emplace_back(tiles_.at(ix));
  Assert(tiles.size() == 13);
  return tiles;
}
'''
INITIAL_HAND_REPLACEMENT = '''std::vector<Tile> Wall::initial_hand_tiles(AbsolutePos pos) const {
  const int players = rule_.num_players();
  const int pos_ix = static_cast<int>(ToUType(pos));
  const int dealer_relative =
      ((pos_ix % players - static_cast<int>(round_ % players) + players) % players);
  int ix = dealer_relative * 4;
  std::vector<Tile> tiles;
  tiles.reserve(13);
  for (int i = 0; i < 3; ++i) {
    for (int j = 0; j < 4; ++j) tiles.emplace_back(tiles_.at(ix++));
    ix += (players - 1) * 4;
  }
  ix = players * 12 + dealer_relative;
  tiles.emplace_back(tiles_.at(ix));
  Assert(tiles.size() == 13);
  return tiles;
}
'''

KAN_DRAW_ANCHOR = '''  auto kan_ixs = std::vector<int>{134, 135, 132, 133};
  auto drawn_tile = tiles_[kan_ixs[num_kan_draw_++]];
'''
KAN_DRAW_REPLACEMENT = '''  const int n = static_cast<int>(tiles_.size());
  const auto kan_ixs = std::vector<int>{n - 2, n - 1, n - 4, n - 3};
  auto drawn_tile = tiles_[kan_ixs[num_kan_draw_++]];
'''

ADD_DORA_ANCHOR = '''  auto kan_dora_indicator = tiles_[130 - 2 * num_kan_dora_];
  auto ura_kan_dora_indicator = tiles_[131 - 2 * num_kan_dora_];
'''
ADD_DORA_REPLACEMENT = '''  auto kan_dora_indicator = tiles_[dora_base_ix() - 2 * num_kan_dora_];
  auto ura_kan_dora_indicator = tiles_[dora_base_ix() + 1 - 2 * num_kan_dora_];
'''

DRAW_LEFT_ANCHOR = '''bool Wall::HasDrawLeft() const {
  Assert(abs(num_kan_draw_ - num_kan_dora_) <= 1);
  return draw_ix_ + num_kan_draw_ < 122;
}

bool Wall::HasNextDrawLeft() const { return draw_ix_ + num_kan_draw_ <= 118; }
'''
DRAW_LEFT_REPLACEMENT = '''bool Wall::HasDrawLeft() const {
  Assert(abs(num_kan_draw_ - num_kan_dora_) <= 1);
  return draw_ix_ + num_kan_draw_ < live_wall_end();
}

bool Wall::HasNextDrawLeft() const {
  return draw_ix_ + num_kan_draw_ <= live_wall_end() - 4;
}
'''

DORA_ANCHOR = '''std::vector<Tile> Wall::dora_indicators() const {
  Assert(abs(num_kan_draw_ - num_kan_dora_) <= 1);
  std::vector<Tile> ret = {tiles_[130]};
  for (int i = 0; i < num_kan_dora_; ++i) ret.emplace_back(tiles_[128 - 2 * i]);
  return ret;
}

std::vector<Tile> Wall::ura_dora_indicators() const {
  Assert(abs(num_kan_draw_ - num_kan_dora_) <= 1);
  std::vector<Tile> ret = {tiles_[131]};
  for (int i = 0; i < num_kan_dora_; ++i) ret.emplace_back(tiles_[129 - 2 * i]);
  return ret;
}
'''
DORA_REPLACEMENT = '''std::vector<Tile> Wall::dora_indicators() const {
  Assert(abs(num_kan_draw_ - num_kan_dora_) <= 1);
  std::vector<Tile> ret = {tiles_[dora_base_ix()]};
  for (int i = 0; i < num_kan_dora_; ++i)
    ret.emplace_back(tiles_[dora_base_ix() - 2 - 2 * i]);
  return ret;
}

std::vector<Tile> Wall::ura_dora_indicators() const {
  Assert(abs(num_kan_draw_ - num_kan_dora_) <= 1);
  std::vector<Tile> ret = {tiles_[dora_base_ix() + 1]};
  for (int i = 0; i < num_kan_dora_; ++i)
    ret.emplace_back(tiles_[dora_base_ix() - 1 - 2 * i]);
  return ret;
}
'''

HELPER_ANCHOR = '''std::uint64_t Wall::game_seed() const { return game_seed_.game_seed(); }
'''
HELPER_REPLACEMENT = '''int Wall::live_wall_end() const noexcept {
  return static_cast<int>(tiles_.size()) - rule_.dead_wall_tiles;
}

int Wall::dora_base_ix() const noexcept {
  return static_cast<int>(tiles_.size()) - 6;
}

std::uint64_t Wall::game_seed() const { return game_seed_.game_seed(); }
'''


def replace_once(path: Path, anchor: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return
    if text.count(anchor) != 1:
        raise RuntimeError(f"Patch anchor mismatch in {path}: {anchor[:80]!r}")
    path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")


def git_blob_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "hash-object", str(path)], check=True, capture_output=True, text=True
    ).stdout.strip()


def apply(root: Path) -> None:
    wall_h = root / "include/mjx/internal/wall.h"
    wall_cpp = root / "include/mjx/internal/wall.cpp"
    if not (root / "include/mjx/internal/rule.h").exists():
        raise RuntimeError("Stage 1 must be applied before stage 2")

    if "const RuleConfig& rule" not in wall_h.read_text(encoding="utf-8"):
        expected_h = "7d66fe3d1d77193359b8d3c75bbfefc99454e6aa"
        expected_cpp = "aee1fb0ae094e1b9b5e90495ac0727ce91bec19a"
        if git_blob_sha(wall_h) != expected_h or git_blob_sha(wall_cpp) != expected_cpp:
            raise RuntimeError("Refusing to patch wall files that do not match pinned MJX v0.1.0")

    replace_once(wall_h, WALL_H_CTOR_ANCHOR, WALL_H_CTOR_REPLACEMENT)
    replace_once(wall_h, WALL_H_PRIVATE_ANCHOR, WALL_H_PRIVATE_REPLACEMENT)
    replace_once(wall_cpp, CTOR_ANCHOR, CTOR_REPLACEMENT)
    replace_once(wall_cpp, INITIAL_HAND_ANCHOR, INITIAL_HAND_REPLACEMENT)
    replace_once(wall_cpp, KAN_DRAW_ANCHOR, KAN_DRAW_REPLACEMENT)
    replace_once(wall_cpp, ADD_DORA_ANCHOR, ADD_DORA_REPLACEMENT)
    replace_once(wall_cpp, DRAW_LEFT_ANCHOR, DRAW_LEFT_REPLACEMENT)
    replace_once(wall_cpp, DORA_ANCHOR, DORA_REPLACEMENT)
    replace_once(wall_cpp, HELPER_ANCHOR, HELPER_REPLACEMENT)

    text = wall_cpp.read_text(encoding="utf-8")
    forbidden = ("% 4", "< 122", "<= 118", "tiles_[130]", "tiles_[131]")
    left = [token for token in forbidden if token in text]
    if left:
        raise RuntimeError(f"Wall generalization postcondition failed: {left}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    apply(args.root.resolve())
    print("MJX_SANMA_STAGE2_OK dynamic 3P/4P wall + deal + dead wall")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
