-- Update database views to include is_notional_capped and cleared fields

CREATE OR REPLACE VIEW arbs_swaption_display_items_v1 AS
SELECT
  p.package_id,
  p.package_type,
  p.as_of_date,
  p.execution_start,
  p.execution_end,
  p.expiration_date,
  p.underlying_expiration_date,
  p.tenor_label,
  p.forward_label,
  p.legs_count,
  p.total_notional,
  p.economic_notional,
  p.total_premium,
  p.package_indicator,
  p.package_transaction_price,
  p.package_confidence,
  p.package_reason,
  p.vega_curve_id,
  p.vega_curve_type,
  p.package_metrics,
  l.legs_json
FROM arbs_swaption_packages_v1 p
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'trade_id', l.trade_id,
            'leg_order', l.leg_order,
            'product_type', l.product_type,
            'trade_label', l.trade_label,
            'strike', l.strike,
            'notional', l.notional,
            'notional_currency', l.notional_currency,
            'is_notional_capped', l.is_notional_capped,
            'premium', l.premium,
            'exercise_style', l.exercise_style,
            'cleared', l.cleared,
            'package_type', l.package_type,
            'leg_metrics', l.leg_metrics
        ) ORDER BY l.leg_order
    ) AS legs_json
    FROM arbs_swaption_legs_v1 l
    WHERE l.package_id = p.package_id
) l ON TRUE;

CREATE OR REPLACE VIEW arbs_swaption_display_items_v2 AS
SELECT
  p.package_id,
  p.package_type,
  p.package_source,
  ml.link_id,
  ml.manual_package_id,
  ml.user_comment,
  ml.link_reason,
  ml.tags,
  ml.created_by AS link_created_by,
  ml.created_at AS link_created_at,
  ml.link_metrics,
  p.as_of_date,
  p.execution_start,
  p.execution_end,
  p.expiration_date,
  p.underlying_expiration_date,
  p.tenor_label,
  p.forward_label,
  p.legs_count,
  p.total_notional,
  p.economic_notional,
  p.total_premium,
  p.package_indicator,
  p.package_transaction_price,
  p.package_confidence,
  p.package_reason,
  p.vega_curve_id,
  p.vega_curve_type,
  p.package_metrics,
  l.legs_json
FROM arbs_swaption_packages_v1 p
LEFT JOIN arbs_swaption_manual_links_v1 ml
  ON p.manual_link_id = ml.link_id AND ml.is_active = TRUE
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'trade_id', l.trade_id,
            'leg_order', l.leg_order,
            'product_type', l.product_type,
            'trade_label', l.trade_label,
            'strike', l.strike,
            'notional', l.notional,
            'notional_currency', l.notional_currency,
            'is_notional_capped', l.is_notional_capped,
            'premium', l.premium,
            'exercise_style', l.exercise_style,
            'cleared', l.cleared,
            'package_type', l.package_type,
            'leg_metrics', l.leg_metrics,
            'is_manually_linked', l.is_manually_linked,
            'manual_link_id', l.manual_link_id
        ) ORDER BY l.leg_order
    ) AS legs_json
    FROM arbs_swaption_legs_v1 l
    WHERE l.package_id = p.package_id
) l ON TRUE;
