#!/usr/bin/env bash
# Independent re-run of the whole mutation battery against the FIXED code.
# No file on disk is edited: every mutation rebinds module attributes in a
# pytest plugin, same mechanism the review validated.
cd "C:/Users/chris/clee/ARBS-dd" || exit 1
export PYTHONPATH="C:/Users/chris/clee/ARBS-dd/scratch"
export ARBS_SUPABASE_ENABLED=0
PY="C:/Users/chris/anaconda3/envs/stir/python.exe"
T="tests/test_dealer_direction_ladder.py"

run() {   # run <plugin> <mutation>
  out=$("$PY" -m pytest "$T" -q --no-header -p no:cacheprovider -p "$1" 2>&1)
  rc=$?
  line=$(printf '%s' "$out" | grep -oE "[0-9]+ failed, [0-9]+ passed|[0-9]+ passed" | tail -1)
  if printf '%s' "$out" | grep -q "anchor not found\|unknown DDREV_MUT\|INTERNALERROR\|SystemExit"; then
    printf '%-42s :: HARNESS-PROBLEM (rc=%s)\n' "$2" "$rc"
    printf '%s' "$out" | grep -E "anchor not found|unknown DDREV_MUT|Error" | head -2
    return
  fi
  if [ -z "$line" ]; then
    printf '%-42s :: NO-SUMMARY (rc=%s)\n' "$2" "$rc"; return
  fi
  if printf '%s' "$line" | grep -q failed; then
    printf '%-42s :: KILLED   (%s)\n' "$2" "$line"
    printf '%s' "$out" | grep '^FAILED' | sed 's/^FAILED tests\/test_dealer_direction_ladder.py::/      -> /'
  else
    printf '%-42s :: SURVIVED (%s)\n' "$2" "$line"
  fi
}

echo "===== batch A: ddrev2_mut (m2-m23) ====="
for m in m2_weight_guard_noop m3_orient_abs m4_weight_is_p m5_decay_row_order \
         m6_kappa_is_hit_rate m7_hole_always_false m8_drop_series_key \
         m9_no_dup_check m10_served_all_true m11_no_placebo \
         m12_dead_zone_one_sided m13_report_lag_pools m14_basis_ok \
         m15_naive_proxy m16_vintage_code_only m17_build_drops_failure \
         m18_visibility_naive_as_utc m19_no_missing_size_check \
         m20_mean_weight_is_one m21_no_krd_double_sign_guard \
         m22_lifecycle_series_ignored m23_no_risk_row_silently_dropped; do
  DDREV_MUT="$m" run ddrev2_mut "$m"
done

echo "===== batch B: ddrev2_mut_b (m24-m34) -- NO saved rerun existed ====="
for m in m24_series_disjoint_noop m25_interdealer_returns_d2c \
         m26_in_session_over_policy_blind m27_health_report_best_first \
         m28_past_start_not_clamped m29_orient_allows_zero_sign \
         m30_missing_call_silently_skipped m31_degenerate_scores_one \
         m32_abs_dv01_is_abs_delta m33_dead_zone_flag_ignored \
         m34_lag_dist_drops_unserved; do
  DDREV_MUT="$m" run ddrev2_mut_b "$m"
done

echo "===== batch C: ddrev2_mut_c (m35-m38) ====="
for m in m35_no_dv01_escalation m36_no_abs_dead_zone_override \
         m37_hole_lag_p90_untested m38_kappa_alarm_uses_warn_only; do
  DDREV_MUT="$m" run ddrev2_mut_c "$m"
done

echo "===== batch D: ladderfix_m6 (re-anchored + new) ====="
for m in m6b_kappa_is_hit_rate m39_degenerate_only_when_chance_is_one \
         m40_hole_reads_max_lag_only m41_build_getattr_defaults \
         m42_ladder_excluded_ignored m43_no_orphan_krd_check \
         m44_no_duplicate_unit_check m45_rolling_empty_one_column; do
  DDREV_MUT="$m" run ladderfix_m6 "$m"
done
echo "===== done ====="
