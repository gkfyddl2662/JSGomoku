from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


STATE_H_SHA = "f5735475b3aed0cc1732db3a826ed0a02a94d8eb"
STATE_CPP_SHA = "e184288b745b387ac9e755f1fe1e3d657b06a0b0"
WIN_SCORE_H_SHA = "2a5069709c00b00c73a0ab4730de0d7dc55921a9"
WIN_SCORE_CPP_SHA = "7e29ce172d30687a45bcbc443eb781076e801075"


def git_blob_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "hash-object", str(path)], check=True, capture_output=True, text=True
    ).stdout.strip()


def require_sha(path: Path, expected: str) -> None:
    actual = git_blob_sha(path)
    if actual != expected:
        raise RuntimeError(
            f"Refusing Stage 4 on unexpected upstream {path}: expected {expected}, got {actual}"
        )


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_ix = text.find(start)
    if start_ix < 0:
        if replacement in text:
            return text
        raise RuntimeError(f"{label}: start marker not found")
    end_ix = text.find(end, start_ix + len(start))
    if end_ix < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start_ix] + replacement.rstrip() + "\n\n" + text[end_ix:]


def edit_between(text: str, start: str, end: str, edits: list[tuple[str, str]], label: str) -> str:
    start_ix = text.find(start)
    end_ix = text.find(end, start_ix + len(start)) if start_ix >= 0 else -1
    if start_ix < 0 or end_ix < 0:
        raise RuntimeError(f"{label}: function markers not found")
    segment = text[start_ix:end_ix]
    for old, new in edits:
        if old in segment:
            segment = segment.replace(old, new)
        elif new not in segment:
            raise RuntimeError(f"{label}: edit anchor missing: {old[:80]!r}")
    return text[:start_ix] + segment + text[end_ix:]


STATE_CONSTRUCTOR = r'''State::State(std::vector<PlayerId> player_ids, std::uint64_t game_seed,
             int round, int honba, int riichi, std::array<int, 4> tens,
             RuleConfig rule)
    : rule_(rule), wall_(round, honba, game_seed, rule) {
  const int n = num_players();
  Assert(static_cast<int>(std::set<PlayerId>(player_ids.begin(), player_ids.end()).size()) == n);
  Assert(static_cast<int>(player_ids.size()) == n);
  Assert(game_seed != 0 && wall_.game_seed() != 0,
         "Seed cannot be zero. round = " + std::to_string(round) +
             ", honba = " + std::to_string(honba));

  for (int i = 0; i < n; ++i) {
    auto hand = Hand(wall_.initial_hand_tiles(AbsolutePos(i)));
    players_[i] = Player{player_ids[i], AbsolutePos(i), std::move(hand)};
  }
  state_.mutable_hidden_state()->set_game_seed(game_seed);
  state_.mutable_public_observation()->set_game_id(
      boost::uuids::to_string(boost::uuids::random_generator()()));
  for (int i = 0; i < n; ++i)
    state_.mutable_public_observation()->add_player_ids(player_ids[i]);
  state_.mutable_public_observation()->mutable_init_score()->set_round(round);
  state_.mutable_public_observation()->mutable_init_score()->set_honba(honba);
  state_.mutable_public_observation()->mutable_init_score()->set_riichi(riichi);
  for (int i = 0; i < n; ++i)
    state_.mutable_public_observation()->mutable_init_score()->add_tens(tens[i]);
  curr_score_.CopyFrom(state_.public_observation().init_score());
  for (auto t : wall_.tiles())
    state_.mutable_hidden_state()->mutable_wall()->Add(t.Id());
  state_.mutable_public_observation()->add_dora_indicators(
      wall_.dora_indicators().front().Id());
  state_.mutable_hidden_state()->add_ura_dora_indicators(
      wall_.ura_dora_indicators().front().Id());
  for (int i = 0; i < n; ++i) {
    state_.add_private_observations()->set_who(i);
    for (const auto tile : wall_.initial_hand_tiles(AbsolutePos(i)))
      state_.mutable_private_observations(i)
          ->mutable_init_hand()
          ->mutable_closed_tiles()
          ->Add(tile.Id());
  }

  Draw(dealer());
  for (int i = 0; i < n; ++i) SyncCurrHand(AbsolutePos(i));
}'''

RESULT_FUNCTION = r'''GameResult State::result() const {
  const auto final_tens = tens();
  const int n = num_players();
  std::vector<std::pair<int, int>> pos_ten;
  for (int i = 0; i < n; ++i) {
    pos_ten.emplace_back(i, final_tens[i] + (n - i));
  }
  std::sort(pos_ten.begin(), pos_ten.end(),
            [](auto x, auto y) { return x.second < y.second; });
  std::reverse(pos_ten.begin(), pos_ten.end());
  for (int i = 0; i + 1 < n; ++i)
    Assert(pos_ten[i].second > pos_ten[i + 1].second);

  std::map<PlayerId, int> rankings;
  std::map<PlayerId, int> tens_map;
  for (int i = 0; i < n; ++i) {
    const int pos = pos_ten[i].first;
    rankings[player(AbsolutePos(pos)).player_id] = i + 1;
    tens_map[player(AbsolutePos(i)).player_id] = final_tens[i];
  }
  return GameResult{game_seed(), rankings, tens_map};
}'''

NO_WINNER_FUNCTION = r'''void State::NoWinner(mjxproto::EventType nowinner_type) {
  Assert(!state_.has_round_terminal(), "Round terminal should not be set");
  const int n = num_players();
  std::optional<AbsolutePos> three_ronned_player = std::nullopt;
  switch (nowinner_type) {
    case mjxproto::EVENT_TYPE_ABORTIVE_DRAW_NINE_TERMINALS: {
      assert(IsFirstTurnWithoutOpen() &&
             LastEvent().type() == mjxproto::EVENT_TYPE_DRAW);
      mjxproto::TenpaiHand tenpai;
      tenpai.set_who(LastEvent().who());
      tenpai.mutable_hand()->CopyFrom(
          hand(AbsolutePos(LastEvent().who())).ToProto());
      state_.mutable_round_terminal()
          ->mutable_no_winner()
          ->mutable_tenpais()
          ->Add(std::move(tenpai));
      state_.mutable_round_terminal()->mutable_final_score()->CopyFrom(curr_score_);
      for (int i = 0; i < n; ++i)
        state_.mutable_round_terminal()->mutable_no_winner()->add_ten_changes(0);
      state_.mutable_public_observation()->mutable_events()->Add(
          Event::CreateAbortiveDrawNineTerminals(
              static_cast<AbsolutePos>(LastEvent().who())));
      return;
    }
    case mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_WINDS: {
      Assert(!rule_.IsSanma(), "Four-winds abortive draw does not exist in sanma");
      assert(IsFourWinds());
      state_.mutable_round_terminal()->mutable_final_score()->CopyFrom(curr_score_);
      for (int i = 0; i < n; ++i)
        state_.mutable_round_terminal()->mutable_no_winner()->add_ten_changes(0);
      state_.mutable_public_observation()->mutable_events()->Add(
          Event::CreateAbortiveDrawFourWinds());
      return;
    }
    case mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_KANS: {
      assert(IsFourKanNoWinner());
      state_.mutable_round_terminal()->mutable_final_score()->CopyFrom(curr_score_);
      for (int i = 0; i < n; ++i)
        state_.mutable_round_terminal()->mutable_no_winner()->add_ten_changes(0);
      state_.mutable_public_observation()->mutable_events()->Add(
          Event::CreateAbortiveDrawFourKans());
      return;
    }
    case mjxproto::EVENT_TYPE_ABORTIVE_DRAW_THREE_RONS: {
      Assert(!rule_.IsSanma(), "Three-ron abortive draw cannot occur with three players");
      assert(LastEvent().type() == mjxproto::EVENT_TYPE_DISCARD or
             LastEvent().type() == mjxproto::EVENT_TYPE_TSUMOGIRI);
      three_ronned_player = static_cast<AbsolutePos>(LastEvent().who());
      state_.mutable_public_observation()->mutable_events()->Add(
          Event::CreateAbortiveDrawThreeRons());
      break;
    }
    case mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_RIICHIS: {
      Assert(!rule_.IsSanma(), "Four-riichi abortive draw does not exist in sanma");
      assert(std::all_of(players_.begin(), players_.begin() + n,
                         [&](const Player &player) {
                           return hand(player.position).IsUnderRiichi();
                         }));
      state_.mutable_public_observation()->mutable_events()->Add(
          Event::CreateAbortiveDrawFourRiichis());
      break;
    }
    case mjxproto::EVENT_TYPE_EXHAUSTIVE_DRAW_NORMAL:
      state_.mutable_public_observation()->mutable_events()->Add(
          Event::CreateExhaustiveDrawNormal());
      break;
    case mjxproto::EVENT_TYPE_EXHAUSTIVE_DRAW_NAGASHI_MANGAN:
      state_.mutable_public_observation()->mutable_events()->Add(
          Event::CreateExhaustiveDrawNagashiMangan());
      break;
    default:
      Assert(false, "impossible state");
  }

  Assert(LastEvent().type() != mjxproto::EVENT_TYPE_EXHAUSTIVE_DRAW_NORMAL ||
         !std::any_of(players_.begin(), players_.begin() + n,
                      [&](const Player &player) {
                        return player.is_ippatsu &&
                               hand(player.position).IsUnderRiichi();
                      }));

  std::vector<int> is_tenpai(n, 0);
  for (int i = 0; i < n; ++i) {
    auto who = AbsolutePos(i);
    if (three_ronned_player && three_ronned_player.value() == who) continue;
    if (hand(who).IsTenpai()) {
      is_tenpai[i] = 1;
      mjxproto::TenpaiHand tenpai;
      tenpai.set_who(ToUType(who));
      tenpai.mutable_hand()->CopyFrom(hand(who).ToProto());
      state_.mutable_round_terminal()
          ->mutable_no_winner()
          ->mutable_tenpais()
          ->Add(std::move(tenpai));
    }
  }

  std::vector<int> ten_move(n, 0);
  const bool has_nagashi = std::any_of(
      players_.begin(), players_.begin() + n,
      [](const Player &p) { return p.has_nm; });
  if (has_nagashi) {
    const int dealer_ix = ToUType(dealer());
    for (int i = 0; i < n; ++i) {
      if (!player(AbsolutePos(i)).has_nm) continue;
      if (rule_.IsSanma()) {
        if (i == dealer_ix) {
          for (int j = 0; j < n; ++j) ten_move[j] += (i == j ? 8000 : -4000);
        } else {
          for (int j = 0; j < n; ++j) {
            if (j == i)
              ten_move[j] += 6000;
            else if (j == dealer_ix)
              ten_move[j] -= 4000;
            else
              ten_move[j] -= 2000;
          }
        }
      } else {
        for (int j = 0; j < n; ++j) {
          if (i == j)
            ten_move[j] += (i == dealer_ix ? 12000 : 8000);
          else
            ten_move[j] -= (i == dealer_ix or j == dealer_ix ? 4000 : 2000);
        }
      }
    }
    state_.mutable_public_observation()->mutable_events()->rbegin()->set_type(
        mjxproto::EVENT_TYPE_EXHAUSTIVE_DRAW_NAGASHI_MANGAN);
  } else if (!three_ronned_player) {
    const int num_tenpai = std::accumulate(is_tenpai.begin(), is_tenpai.end(), 0);
    if (rule_.IsSanma()) {
      if (num_tenpai == 1) {
        for (int i = 0; i < n; ++i) ten_move[i] = is_tenpai[i] ? 2000 : -1000;
      } else if (num_tenpai == 2) {
        for (int i = 0; i < n; ++i) ten_move[i] = is_tenpai[i] ? 1000 : -2000;
      }
    } else {
      for (int i = 0; i < n; ++i) {
        switch (num_tenpai) {
          case 1: ten_move[i] = is_tenpai[i] ? 3000 : -1000; break;
          case 2: ten_move[i] = is_tenpai[i] ? 1500 : -1500; break;
          case 3: ten_move[i] = is_tenpai[i] ? 1000 : -3000; break;
          default: ten_move[i] = 0; break;
        }
      }
    }
  }

  for (int i = 0; i < n; ++i) {
    state_.mutable_round_terminal()->mutable_no_winner()->add_ten_changes(ten_move[i]);
    curr_score_.set_tens(i, ten(AbsolutePos(i)) + ten_move[i]);
  }

  if (IsGameOver()) {
    AbsolutePos top = top_player();
    curr_score_.set_tens(ToUType(top),
                         curr_score_.tens(ToUType(top)) + 1000 * riichi());
    curr_score_.set_riichi(0);
  }
  state_.mutable_round_terminal()->set_is_game_over(IsGameOver());
  state_.mutable_round_terminal()->mutable_final_score()->CopyFrom(curr_score_);
}'''

IS_GAME_OVER_FUNCTION = r'''bool State::IsGameOver() const {
  Assert(IsRoundOver(),
         "State::IsGameOver() should be called only when round reached the end.");
  const int max_rounds = rule_.rounds_per_wind * 3;
  Assert(round() < max_rounds, "Round exceeds configured east/south/west range.");

  auto last_event_type = LastEvent().type();
  bool is_dealer_win_or_tenpai =
      (Any(last_event_type,
           {mjxproto::EVENT_TYPE_RON, mjxproto::EVENT_TYPE_TSUMO}) &&
       std::any_of(state_.round_terminal().wins().begin(),
                   state_.round_terminal().wins().end(),
                   [&](const auto x) { return AbsolutePos(x.who()) == dealer(); })) ||
      (Any(last_event_type,
           {mjxproto::EVENT_TYPE_ABORTIVE_DRAW_NINE_TERMINALS,
            mjxproto::EVENT_TYPE_ABORTIVE_DRAW_THREE_RONS,
            mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_KANS,
            mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_WINDS,
            mjxproto::EVENT_TYPE_EXHAUSTIVE_DRAW_NORMAL,
            mjxproto::EVENT_TYPE_EXHAUSTIVE_DRAW_NAGASHI_MANGAN}) &&
       std::any_of(state_.round_terminal().no_winner().tenpais().begin(),
                   state_.round_terminal().no_winner().tenpais().end(),
                   [&](const auto x) { return AbsolutePos(x.who()) == dealer(); }));

  std::optional<mjxproto::EventType> no_winner_type;
  if (!Any(last_event_type, {mjxproto::EVENT_TYPE_RON, mjxproto::EVENT_TYPE_TSUMO}) &&
      Any(last_event_type,
          {mjxproto::EVENT_TYPE_ABORTIVE_DRAW_NINE_TERMINALS,
           mjxproto::EVENT_TYPE_ABORTIVE_DRAW_THREE_RONS,
           mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_KANS,
           mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_WINDS,
           mjxproto::EVENT_TYPE_EXHAUSTIVE_DRAW_NORMAL,
           mjxproto::EVENT_TYPE_EXHAUSTIVE_DRAW_NAGASHI_MANGAN})) {
    no_winner_type = last_event_type;
  }

  return CheckGameOver(round(), tens(), dealer(), is_dealer_win_or_tenpai,
                       no_winner_type, rule_);
}'''

CHECK_GAME_OVER_FUNCTION = r'''bool State::CheckGameOver(
    int round, std::array<int, 4> tens, AbsolutePos dealer,
    bool is_dealer_win_or_tenpai,
    std::optional<mjxproto::EventType> no_winner_type,
    const RuleConfig& rule) noexcept {
  if (no_winner_type.has_value() &&
      Any(no_winner_type, {mjxproto::EVENT_TYPE_ABORTIVE_DRAW_NINE_TERMINALS,
                           mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_RIICHIS,
                           mjxproto::EVENT_TYPE_ABORTIVE_DRAW_THREE_RONS,
                           mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_KANS,
                           mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_WINDS})) {
    return false;
  }

  const int n = rule.num_players();
  for (int i = 0; i < n; ++i) tens[i] += n - i;
  const auto active_begin = tens.begin();
  const auto active_end = tens.begin() + n;
  const auto top_score = *std::max_element(active_begin, active_end);

  if (*std::min_element(active_begin, active_end) < 0) return true;

  const int south_last = 2 * rule.rounds_per_wind - 1;
  const int west_last = 3 * rule.rounds_per_wind - 1;
  if (round < south_last) return false;

  const bool dealer_is_not_top = top_score != tens[ToUType(dealer)];
  if (round >= west_last) {
    return !(is_dealer_win_or_tenpai && dealer_is_not_top);
  }

  const bool top_reached_return = top_score >= rule.return_points;
  if (!top_reached_return) return false;

  return !(is_dealer_win_or_tenpai && dealer_is_not_top);
}'''

NEXT_FUNCTION = r'''State::ScoreInfo State::Next() const {
  Assert(!IsGameOver());
  std::vector<PlayerId> player_ids(
      state_.public_observation().player_ids().begin(),
      state_.public_observation().player_ids().end());
  const int max_rounds = rule_.rounds_per_wind * 3;
  if (Any(LastEvent().type(),
          {mjxproto::EVENT_TYPE_ABORTIVE_DRAW_NINE_TERMINALS,
           mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_RIICHIS,
           mjxproto::EVENT_TYPE_ABORTIVE_DRAW_THREE_RONS,
           mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_KANS,
           mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_WINDS,
           mjxproto::EVENT_TYPE_EXHAUSTIVE_DRAW_NORMAL,
           mjxproto::EVENT_TYPE_EXHAUSTIVE_DRAW_NAGASHI_MANGAN})) {
    bool is_dealer_tenpai = std::any_of(
        state_.round_terminal().no_winner().tenpais().begin(),
        state_.round_terminal().no_winner().tenpais().end(),
        [&](const auto x) { return AbsolutePos(x.who()) == dealer(); });
    const bool abortive = Any(
        LastEvent().type(),
        {mjxproto::EVENT_TYPE_ABORTIVE_DRAW_NINE_TERMINALS,
         mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_RIICHIS,
         mjxproto::EVENT_TYPE_ABORTIVE_DRAW_THREE_RONS,
         mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_KANS,
         mjxproto::EVENT_TYPE_ABORTIVE_DRAW_FOUR_WINDS});
    if (abortive || is_dealer_tenpai) {
      return ScoreInfo{player_ids, game_seed(), round(), honba() + 1,
                       riichi(), tens(), rule_};
    }
    Assert(round() + 1 < max_rounds, "round exceeds configured range. State:\n" + ToJson());
    return ScoreInfo{player_ids, game_seed(), round() + 1, honba() + 1,
                     riichi(), tens(), rule_};
  }

  bool is_dealer_win = std::any_of(
      state_.round_terminal().wins().begin(),
      state_.round_terminal().wins().end(),
      [&](const auto x) { return AbsolutePos(x.who()) == dealer(); });
  if (is_dealer_win) {
    return ScoreInfo{player_ids, game_seed(), round(), honba() + 1,
                     riichi(), tens(), rule_};
  }
  Assert(round() + 1 < max_rounds, "round exceeds configured range. State:\n" + ToJson());
  return ScoreInfo{player_ids, game_seed(), round() + 1, 0,
                   riichi(), tens(), rule_};
}'''

FIRST_TURN_AND_WINDS = r'''bool State::IsFirstTurnWithoutOpen() const {
  int discards = 0;
  for (const auto &event : state_.public_observation().events()) {
    switch (event.type()) {
      case mjxproto::EVENT_TYPE_CHI:
      case mjxproto::EVENT_TYPE_PON:
      case mjxproto::EVENT_TYPE_CLOSED_KAN:
      case mjxproto::EVENT_TYPE_OPEN_KAN:
      case mjxproto::EVENT_TYPE_ADDED_KAN:
        return false;
      case mjxproto::EVENT_TYPE_DISCARD:
      case mjxproto::EVENT_TYPE_TSUMOGIRI:
        if (++discards >= num_players()) return false;
        break;
      default:
        break;
    }
  }
  return true;
}

bool State::IsFourWinds() const {
  if (rule_.IsSanma()) return false;
  std::map<TileType, int> discarded_winds;
  for (const auto &event : state_.public_observation().events()) {
    switch (event.type()) {
      case mjxproto::EVENT_TYPE_CHI:
      case mjxproto::EVENT_TYPE_PON:
      case mjxproto::EVENT_TYPE_CLOSED_KAN:
      case mjxproto::EVENT_TYPE_OPEN_KAN:
      case mjxproto::EVENT_TYPE_ADDED_KAN:
        return false;
      case mjxproto::EVENT_TYPE_DISCARD:
      case mjxproto::EVENT_TYPE_TSUMOGIRI:
        if (!Is(Tile(event.tile()).Type(), TileSetType::kWinds)) return false;
        ++discarded_winds[Tile(event.tile()).Type()];
        if (discarded_winds.size() > 1) return false;
        break;
      default:
        break;
    }
  }
  return discarded_winds.size() == 1 &&
         discarded_winds.begin()->second == num_players();
}'''

TOP_PLAYER_FUNCTION = r'''AbsolutePos State::top_player() const {
  int top_ix = 0;
  int top_ten = INT_MIN;
  const int n = num_players();
  for (int i = 0; i < n; ++i) {
    int ten = curr_score_.tens(i) + (n - i);
    if (top_ten < ten) {
      top_ix = i;
      top_ten = ten;
    }
  }
  return AbsolutePos(top_ix);
}'''

FOUR_KAN_FUNCTION = r'''bool State::IsFourKanNoWinner() const noexcept {
  std::vector<int> kans;
  for (int i = 0; i < num_players(); ++i) {
    const Player &p = players_[i];
    if (int num = hand(p.position).TotalKans(); num) kans.emplace_back(num);
  }
  return std::accumulate(kans.begin(), kans.end(), 0) == 4 && kans.size() > 1;
}'''

HAS_PAO_FUNCTION = r'''std::optional<AbsolutePos> State::HasPao(AbsolutePos winner) const noexcept {
  auto pao = player(winner).hand.HasPao();
  if (pao)
    return AbsolutePos((ToUType(winner) + ToUType(pao.value())) % num_players());
  return std::nullopt;
}'''

SET_INIT_STATE_FUNCTION = r'''void State::SetInitState(const mjxproto::State &proto, State &state) {
  state.state_.mutable_public_observation()->mutable_player_ids()->CopyFrom(
      proto.public_observation().player_ids());
  state.state_.mutable_public_observation()->mutable_init_score()->CopyFrom(
      proto.public_observation().init_score());
  state.curr_score_.CopyFrom(proto.public_observation().init_score());

  auto wall_tiles = std::vector<Tile>();
  for (auto tile_id : proto.hidden_state().wall()) wall_tiles.emplace_back(Tile(tile_id));
  state.rule_ = RuleConfig::FromWallSize(wall_tiles.size());
  const int n = state.num_players();
  Assert(proto.public_observation().player_ids_size() == n);
  Assert(proto.public_observation().init_score().tens_size() == n);
  state.wall_ = Wall(state.round(), wall_tiles);
  state.state_.mutable_hidden_state()->mutable_wall()->CopyFrom(
      proto.hidden_state().wall());
  state.state_.mutable_hidden_state()->set_game_seed(proto.hidden_state().game_seed());
  state.state_.mutable_public_observation()->add_dora_indicators(
      state.wall_.dora_indicators().front().Id());
  state.state_.mutable_hidden_state()->add_ura_dora_indicators(
      state.wall_.ura_dora_indicators().front().Id());

  for (int i = 0; i < n; ++i) {
    state.players_[i] =
        Player{state.state_.public_observation().player_ids(i), AbsolutePos(i),
               Hand(state.wall_.initial_hand_tiles(AbsolutePos(i)))};
    state.state_.mutable_private_observations()->Add();
    state.state_.mutable_private_observations(i)->set_who(i);
    for (auto t : state.wall_.initial_hand_tiles(AbsolutePos(i))) {
      state.state_.mutable_private_observations(i)
          ->mutable_init_hand()
          ->mutable_closed_tiles()
          ->Add(t.Id());
    }
    state.state_.mutable_public_observation()->set_game_id(
        proto.public_observation().game_id());
  }

  state.Draw(state.dealer());
  for (int i = 0; i < n; ++i) state.SyncCurrHand(AbsolutePos(i));
}'''


def patch_state_h(text: str) -> str:
    text = replace_once(
        text,
        '#include "mjx/internal/observation.h"\n#include "mjx/internal/tile.h"',
        '#include "mjx/internal/observation.h"\n#include "mjx/internal/rule.h"\n#include "mjx/internal/tile.h"',
        "state rule include",
    )
    text = replace_once(
        text,
        '    std::array<int, 4> tens = {25000, 25000, 25000, 25000};\n',
        '    std::array<int, 4> tens = {25000, 25000, 25000, 25000};\n'
        '    RuleConfig rule = RuleConfig::Yonma();\n',
        "ScoreInfo rule",
    )
    text = replace_once(
        text,
        '  [[nodiscard]] std::uint8_t init_riichi() const;\n',
        '  [[nodiscard]] std::uint8_t init_riichi() const;\n'
        '  [[nodiscard]] int num_players() const noexcept { return rule_.num_players(); }\n'
        '  [[nodiscard]] const RuleConfig& rule() const noexcept { return rule_; }\n',
        "state rule accessors",
    )
    text = replace_once(
        text,
        '                            std::optional<mjxproto::EventType> no_winner_type =\n'
        '                                std::nullopt) noexcept;\n',
        '                            std::optional<mjxproto::EventType> no_winner_type =\n'
        '                                std::nullopt,\n'
        '                            const RuleConfig& rule = RuleConfig::Yonma()) noexcept;\n',
        "CheckGameOver rule",
    )
    text = replace_once(
        text,
        '                 int riichi = 0,\n'
        '                 std::array<int, 4> tens = {25000, 25000, 25000, 25000});\n',
        '                 int riichi = 0,\n'
        '                 std::array<int, 4> tens = {25000, 25000, 25000, 25000},\n'
        '                 RuleConfig rule = RuleConfig::Yonma());\n',
        "private constructor rule",
    )
    text = replace_once(
        text,
        '  // containers\n  Wall wall_;\n',
        '  // containers\n  RuleConfig rule_ = RuleConfig::Yonma();\n  Wall wall_;\n',
        "state rule member",
    )
    return text


def patch_win_score_h(text: str) -> str:
    text = replace_once(
        text,
        '#include "mjx/internal/types.h"',
        '#include "mjx/internal/rule.h"\n#include "mjx/internal/types.h"',
        "win score rule include",
    )
    text = replace_once(
        text,
        '      AbsolutePos winner, AbsolutePos dealer,\n'
        '      std::optional<AbsolutePos> loser = std::nullopt) const noexcept;\n',
        '      AbsolutePos winner, AbsolutePos dealer,\n'
        '      std::optional<AbsolutePos> loser = std::nullopt,\n'
        '      const RuleConfig& rule = RuleConfig::Yonma()) const noexcept;\n',
        "TenMoves rule signature",
    )
    return text


def patch_win_score_cpp(text: str) -> str:
    text = replace_once(
        text,
        'std::map<AbsolutePos, int> WinScore::TenMoves(\n'
        '    AbsolutePos winner, AbsolutePos dealer,\n'
        '    std::optional<AbsolutePos> loser) const noexcept {\n',
        'std::map<AbsolutePos, int> WinScore::TenMoves(\n'
        '    AbsolutePos winner, AbsolutePos dealer,\n'
        '    std::optional<AbsolutePos> loser, const RuleConfig& rule) const noexcept {\n'
        '  const int num_players = rule.num_players();\n',
        "TenMoves cpp signature",
    )
    text = replace_once(
        text,
        '      for (int i = 0; i < 4; ++i)\n'
        '        ten_moves[AbsolutePos(i)] =\n'
        '            AbsolutePos(i) == winner ? 3 * payment : -payment;\n',
        '      for (int i = 0; i < num_players; ++i)\n'
        '        ten_moves[AbsolutePos(i)] = AbsolutePos(i) == winner\n'
        '                                        ? (num_players - 1) * payment\n'
        '                                        : -payment;\n',
        "dealer tsumo active players",
    )
    text = replace_once(
        text,
        '      for (int i = 0; i < 4; ++i) {\n'
        '        auto who = AbsolutePos(i);\n'
        '        if (who == winner)\n'
        '          ten_moves[who] = dealer_payment + 2 * child_payment;\n',
        '      for (int i = 0; i < num_players; ++i) {\n'
        '        auto who = AbsolutePos(i);\n'
        '        if (who == winner)\n'
        '          ten_moves[who] = dealer_payment + (num_players - 2) * child_payment;\n',
        "nondealer tsumo active players",
    )
    return text


def patch_state_cpp(text: str) -> str:
    text = replace_once(
        text,
        '    : State(score_info.player_ids, score_info.game_seed, score_info.round,\n'
        '            score_info.honba, score_info.riichi, score_info.tens) {}\n',
        '    : State(score_info.player_ids, score_info.game_seed, score_info.round,\n'
        '            score_info.honba, score_info.riichi, score_info.tens,\n'
        '            score_info.rule) {}\n',
        "ScoreInfo delegation",
    )
    text = replace_between(
        text,
        'State::State(std::vector<PlayerId> player_ids, std::uint64_t game_seed,',
        'bool State::IsRoundOver() const {',
        STATE_CONSTRUCTOR,
        "state constructor",
    )
    text = replace_between(
        text, 'GameResult State::result() const {',
        'std::unordered_map<PlayerId, Observation> State::CreateObservations() const {',
        RESULT_FUNCTION, "result")
    text = edit_between(
        text,
        'std::unordered_map<PlayerId, Observation> State::CreateObservations() const {',
        'mjxproto::State State::LoadJson',
        [('for (int i = 0; i < 4; ++i) {', 'for (int i = 0; i < num_players(); ++i) {')],
        "CreateObservations",
    )
    text = edit_between(
        text, 'Tile State::Draw(AbsolutePos who) {', 'void State::Discard(',
        [('for (int i = 0; i < 4; ++i) {', 'for (int i = 0; i < num_players(); ++i) {')],
        "Draw",
    )
    text = edit_between(
        text, 'void State::ApplyOpen(AbsolutePos who, Open open) {', 'void State::AddNewDora()',
        [
            ('% 4;', '% num_players();'),
            ('for (int i = 0; i < 4; ++i)', 'for (int i = 0; i < num_players(); ++i)'),
        ],
        "ApplyOpen",
    )
    text = edit_between(
        text, 'void State::Tsumo(AbsolutePos winner) {', 'void State::Ron(AbsolutePos winner) {',
        [
            ('auto ten_moves = win_score.TenMoves(winner, dealer());',
             'auto ten_moves = win_score.TenMoves(winner, dealer(), std::nullopt, rule_);'),
            ('ten_move += riichi() * 1000 + honba() * 300;',
             'ten_move += riichi() * 1000 + honba() * 100 * (num_players() - 1);'),
            ('ten_move = -ten_ - honba() * 300;',
             'ten_move = -ten_ - honba() * 100 * (num_players() - 1);'),
            ('for (int i = 0; i < 4; ++i) win.add_ten_changes(0);',
             'for (int i = 0; i < num_players(); ++i) win.add_ten_changes(0);'),
        ],
        "Tsumo",
    )
    text = edit_between(
        text, 'void State::Ron(AbsolutePos winner) {', 'void State::NoWinner(',
        [
            ('auto ten_moves = win_score.TenMoves(winner, dealer(), loser);',
             'auto ten_moves = win_score.TenMoves(winner, dealer(), loser, rule_);'),
            ('for (int i = 0; i < 4; ++i) win.add_ten_changes(0);',
             'for (int i = 0; i < num_players(); ++i) win.add_ten_changes(0);'),
        ],
        "Ron",
    )
    text = replace_between(text, 'void State::NoWinner(', 'bool State::IsGameOver() const {',
                           NO_WINNER_FUNCTION, "NoWinner")
    text = replace_between(text, 'bool State::IsGameOver() const {', 'bool State::CheckGameOver(',
                           IS_GAME_OVER_FUNCTION, "IsGameOver")
    text = replace_between(text, 'bool State::CheckGameOver(', 'std::pair<State::HandInfo, WinScore> State::EvalWinHand(',
                           CHECK_GAME_OVER_FUNCTION, "CheckGameOver")
    text = replace_once(
        text,
        'AbsolutePos State::dealer() const {\n  return AbsolutePos(state_.public_observation().init_score().round() % 4);\n}',
        'AbsolutePos State::dealer() const {\n  return AbsolutePos(state_.public_observation().init_score().round() % num_players());\n}',
        "dealer active players",
    )
    text = edit_between(
        text, 'std::array<std::int32_t, 4> State::tens() const {', 'Wind State::prevalent_wind() const {',
        [('for (int i = 0; i < 4; ++i)', 'for (int i = 0; i < num_players(); ++i)')],
        "tens accessor",
    )
    text = replace_once(
        text,
        'Wind State::prevalent_wind() const { return Wind(round() / 4); }',
        'Wind State::prevalent_wind() const { return Wind(round() / rule_.rounds_per_wind); }',
        "prevalent wind",
    )
    text = replace_between(text, 'State::ScoreInfo State::Next() const {',
                           'std::uint8_t State::init_riichi() const {', NEXT_FUNCTION, "Next")
    text = edit_between(
        text, 'std::array<std::int32_t, 4> State::init_tens() const {', 'bool State::HasLastEvent() const {',
        [('for (int i = 0; i < 4; ++i)', 'for (int i = 0; i < num_players(); ++i)')],
        "init tens",
    )
    text = replace_between(text, 'bool State::IsFirstTurnWithoutOpen() const {',
                           'bool State::IsRobbingKan() const {', FIRST_TURN_AND_WINDS,
                           "first turn / four winds")
    text = edit_between(
        text, 'std::unordered_map<PlayerId, Observation> State::CreateStealAndRonObservation()',
        'WinStateInfo State::win_state_info(',
        [('for (int i = 0; i < 4; ++i) {', 'for (int i = 0; i < num_players(); ++i) {')],
        "steal and ron observations",
    )
    text = edit_between(
        text, 'void State::Update(std::vector<mjxproto::Action> &&action_candidates) {',
        'void State::Update(mjxproto::Action &&action) {',
        [
            ('Assert(action_candidates.size() == 4);',
             'Assert(action_candidates.size() == static_cast<std::size_t>(num_players()));'),
            ('Assert(action_candidates.size() <= 3);',
             'Assert(action_candidates.size() <= static_cast<std::size_t>(num_players() - 1));'),
            ('((x.who() - from_who + 4) % 4) <\n                     ((y.who() - from_who + 4) % 4)',
             '((x.who() - from_who + num_players()) % num_players()) <\n                     ((y.who() - from_who + num_players()) % num_players())'),
            ('if (ron_count == 3) {', 'if (!rule_.IsSanma() && ron_count == 3) {'),
        ],
        "multi action Update",
    )
    text = edit_between(
        text, 'void State::Update(mjxproto::Action &&action) {', 'AbsolutePos State::top_player() const {',
        [
            ('std::all_of(players_.begin(), players_.end(),',
             'std::all_of(players_.begin(), players_.begin() + num_players(),'),
            ('Draw(AbsolutePos((ToUType(who) + 1) % 4));',
             'Draw(AbsolutePos((ToUType(who) + 1) % num_players()));'),
            ('Draw(AbsolutePos((LastEvent().who() + 1) % 4));',
             'Draw(AbsolutePos((LastEvent().who() + 1) % num_players()));'),
            ('if (std::all_of(players_.begin(), players_.begin() + num_players(),',
             'if (!rule_.IsSanma() &&\n          std::all_of(players_.begin(), players_.begin() + num_players(),'),
        ],
        "single action Update",
    )
    text = replace_between(text, 'AbsolutePos State::top_player() const {',
                           'bool State::IsFourKanNoWinner() const noexcept {', TOP_PLAYER_FUNCTION,
                           "top player")
    text = replace_between(text, 'bool State::IsFourKanNoWinner() const noexcept {',
                           'mjxproto::State State::proto() const {', FOUR_KAN_FUNCTION,
                           "four kan")
    text = replace_between(text, 'std::optional<AbsolutePos> State::HasPao(',
                           'bool State::Equals(', HAS_PAO_FUNCTION, "pao")
    text = edit_between(
        text, 'bool State::Equals(', 'bool State::CanReach(',
        [
            ('  auto seq_eq =', '  if (num_players() != other.num_players()) return false;\n  auto seq_eq ='),
            ('for (int i = 0; i < 4; ++i)', 'for (int i = 0; i < num_players(); ++i)'),
        ],
        "Equals",
    )
    text = edit_between(
        text, 'bool State::CanReach(', '// #398',
        [
            ('  auto seq_eq =', '  if (num_players() != other.num_players()) return false;\n  auto seq_eq ='),
            ('for (int i = 0; i < 4; ++i)', 'for (int i = 0; i < num_players(); ++i)'),
        ],
        "CanReach",
    )
    text = edit_between(
        text, 'mjxproto::Observation State::observation(', 'std::string State::ProtoToJson(',
        [('for (int i = 0; i < 4; ++i)', 'for (int i = 0; i < num_players(); ++i)')],
        "observation lookup",
    )
    text = replace_between(text, 'void State::SetInitState(',
                           'std::queue<mjxproto::Action> State::EventsToActions(',
                           SET_INIT_STATE_FUNCTION, "SetInitState")
    text = edit_between(
        text, 'std::queue<mjxproto::Action> State::EventsToActions(',
        'std::vector<std::pair<mjxproto::Observation, mjxproto::Action>>\nState::UpdateByActions(',
        [('for (int i = 0; i < 4; ++i) {',
          'for (int i = 0; i < proto.public_observation().player_ids_size(); ++i) {')],
        "EventsToActions",
    )
    return text


def apply(root: Path) -> None:
    rule_h = root / "include/mjx/internal/rule.h"
    state_h = root / "include/mjx/internal/state.h"
    state_cpp = root / "include/mjx/internal/state.cpp"
    win_score_h = root / "include/mjx/internal/win_score.h"
    win_score_cpp = root / "include/mjx/internal/win_score.cpp"

    if not rule_h.exists():
        raise RuntimeError("Stage 1 must be applied before Stage 4")
    if "RuleConfig rule_" not in state_h.read_text(encoding="utf-8"):
        require_sha(state_h, STATE_H_SHA)
        require_sha(state_cpp, STATE_CPP_SHA)
        require_sha(win_score_h, WIN_SCORE_H_SHA)
        require_sha(win_score_cpp, WIN_SCORE_CPP_SHA)

    state_h.write_text(patch_state_h(state_h.read_text(encoding="utf-8")), encoding="utf-8")
    win_score_h.write_text(patch_win_score_h(win_score_h.read_text(encoding="utf-8")), encoding="utf-8")
    win_score_cpp.write_text(patch_win_score_cpp(win_score_cpp.read_text(encoding="utf-8")), encoding="utf-8")
    state_cpp.write_text(patch_state_cpp(state_cpp.read_text(encoding="utf-8")), encoding="utf-8")

    state_text = state_cpp.read_text(encoding="utf-8")
    score_text = win_score_cpp.read_text(encoding="utf-8")
    required = (
        "RuleConfig rule_",
        "rule_.rounds_per_wind",
        "rule_.return_points",
        "num_players() - 1",
        "rule_.IsSanma()",
        "RuleConfig::FromWallSize",
    )
    combined = state_h.read_text(encoding="utf-8") + state_text + score_text
    missing = [token for token in required if token not in combined]
    if missing:
        raise RuntimeError(f"Stage 4 postconditions missing: {missing}")

    # Stage 4 intentionally leaves chi/nuki action legality to Stage 5, but
    # active-player game flow must no longer use the core modulo-4 draw loop.
    forbidden = (
        "Draw(AbsolutePos((ToUType(who) + 1) % 4))",
        "Draw(AbsolutePos((LastEvent().who() + 1) % 4))",
        "return AbsolutePos(state_.public_observation().init_score().round() % 4)",
        "Wind State::prevalent_wind() const { return Wind(round() / 4); }",
    )
    left = [token for token in forbidden if token in state_text]
    if left:
        raise RuntimeError(f"Stage 4 active-player flow postcondition failed: {left}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    apply(args.root.resolve())
    print("MJX_SANMA_STAGE4_OK rule-aware state + score + round flow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
