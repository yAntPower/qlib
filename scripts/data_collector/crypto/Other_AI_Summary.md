以下内容为其他AI模型的总结：

## 潜在改进（非必须但建议）

1.极小波动保护：当前 sigma < 1e-6 时直接返回原概率；可改为直接返回目标均值（0.5）减少放大量化噪声。
2.分位数 HOLD 置信度：HOLD 区间靠近边界(q20/q80)时可出现置信度接近1但仍 HOLD，若希望 HOLD = 不执行 则可上限如 min(confidence, 0.6)。
3.统一过滤：quantile 分支未再应用 min_confidence / dead_zone，可追加统一后处理。
4.校准统计污染：目前用 adjusted_buy_prob（含 bias）更新分布，建议改为使用 raw_buy_prob（融合模型但未加 bias）以免趋势偏置挤压 σ。
5.span 退化：当 q80≈q20（模型长期输出收敛）应触发回退（否则 HOLD 置信度全是1）。
6.记录 bias：可放入返回字典（方便监控偏置贡献）。
7.初期热身：min_samples_for_quantile=300 在小时级需 ~12.5 天才进入真实分位数模式，可考虑分阶段：<100 用 q30/q70，≥100 用 q25/q75，≥300 用 q20/q80。

## 建议补丁（可选优化）
### 补丁1：更稳健的校准极端处理 + 使用 raw_buy_prob 统计

```python
// filepath: /home/ant/project/qlib/scripts/data_collector/crypto/autogluon_river_strategy.py
// ...existing code...
    def _calibrate_prob(self, symbol: str, p: float) -> float:
        stats = self._feature_stats.get(symbol, {})
        mu = stats.get('prob_mean')
        sigma = stats.get('prob_std')
        if mu is None or sigma is None:
            return p
        if sigma < 5e-4:
            # 分布塌缩时直接回归目标均值，避免放大量化噪声
            return self.calibration_target_mean
        mu_t = self.calibration_target_mean
        sigma_t = self.calibration_target_std
        p_cal = (p - mu) * sigma_t / sigma + mu_t
        return float(np.clip(p_cal, 0, 1))
// ...existing code in generate_signal() near online更新部分...
                # 改为使用 raw_buy_prob（未加 bias）更新统计，避免 bias 污染
                base_prob_for_stats = raw_buy_prob
                stats = self._feature_stats.setdefault(symbol, {})
                raw_mu = stats.get('prob_mean')
                raw_std = stats.get('prob_std')
                alpha = 0.02
                if raw_mu is None:
                    stats['prob_mean'] = float(base_prob_for_stats)
                    stats['prob_std'] = 0.05
                else:
                    prev_mu = stats['prob_mean']
                    new_mu = (1 - alpha) * prev_mu + alpha * base_prob_for_stats
                    new_var = (1 - alpha) * (raw_std ** 2) + alpha * (base_prob_for_stats - new_mu) ** 2
                    stats['prob_mean'] = float(new_mu)
                    stats['prob_std'] = float(np.sqrt(max(new_var, 1e-8)))
// ...existing code...
```
### 补丁2：分位数决策加入 span 退化检测 + 统一 dead_zone / min_confidence
```python
// filepath: /home/ant/project/qlib/scripts/data_collector/crypto/autogluon_river_strategy.py
// ...existing code in _decision_from_quantiles...
        # 使用分位数决策
        arr = np.array(hist)
        q20, q50, q80 = np.quantile(arr, [0.2, 0.5, 0.8])
        span = q80 - q20
        if span < 0.01:  # 分布过窄 → 回退
            # 视为信息不足：直接回退逻辑（保持已有结构）
            median = q50
            iqr = max(q80 - q20, 1e-6)
            confidence = float(np.clip(abs(p - median) / (iqr / 2), 0, 1))
            if confidence < self.dead_zone:
                return 'HOLD', confidence, {'mode': 'quantile_fallback', 'reason': 'span_collapse', 'median': median}
            rec = 'BUY' if p > median else 'SELL'
            if confidence < self.min_confidence:
                return 'HOLD', confidence, {'mode': 'quantile_fallback', 'reason': 'min_conf', 'median': median}
            return rec, confidence, {'mode': 'quantile_fallback', 'median': median}

        # 正常 span 情况
        span = max(span, 1e-6)
        if p > q80:
            rec = 'BUY'
            confidence = 0.5 + 0.5 * min((p - q80) / span, 1.0)
        elif p < q20:
            rec = 'SELL'
            confidence = 0.5 + 0.5 * min((q20 - p) / span, 1.0)
        else:
            rec = 'HOLD'
            confidence = abs(p - q50) / (span / 2)
        confidence = float(np.clip(confidence, 0, 1))

        # 统一过滤（仅对 BUY/SELL 应用 min_confidence）
        if rec != 'HOLD' and (confidence < self.dead_zone or confidence < self.min_confidence):
            return 'HOLD', confidence, {'mode': 'quantile', 'reason': 'filtered', 'q20': float(q20), 'q80': float(q80)}
        # 可选：限制 HOLD 置信度上限
        if rec == 'HOLD':
            confidence = float(min(confidence, 0.6))

        return rec, confidence, {
            'mode': 'quantile',
            'q20': float(q20),
            'q50': float(q50),
            'q80': float(q80),
            'p': float(p)
        }
// ...existing code...
```

## 验证建议（可离线快速检查）

* 校准前后分布：收集 N=500 条 raw_buy_prob 与 buy_prob，比较均值是否从 ~0.07 → ~0.5、标准差是否接近 0.15。
* 分位数逻辑：人工构造概率序列（例如均匀递增）测试边界：p = q80±ε、q20±ε、span→极小场景。
* 触发 span<0.01：伪造 hist=[0.51±0.002 随机噪声] 看是否走回退。
## 结论
当前实现四个核心补丁逻辑正确；系统已具备基本生产可用性。上述改进属增强级建议，不影响现有正确性。若无进一步需求可直接进入回测/小额实盘验证阶段。

需要再做更深层验证可继续说明。