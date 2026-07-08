# M12.3 Risk Register

## Risk: baseline overfits current fixture

Mitigation: M12.3 separates the baseline contract from the report check. Future baselines can be explicitly reviewed without mutating historical artifacts.

## Risk: allowed failure reasons hide regressions

Mitigation: allowed failure reasons default to empty. Any unexpected reason fails closed.

## Risk: broader audience report satisfies narrower baseline

Mitigation: report case audiences are unioned and compared to `approved_audiences`. Extra audiences fail closed with `audience_broadening`.

## Risk: release drift during evaluation

Mitigation: release ID and manifest SHA-256 are checked exactly against the baseline.

## Risk: downstream workflow treats the check as approval

Mitigation: the check emits explicit governance denial flags and documentation states that it is evidence only.
