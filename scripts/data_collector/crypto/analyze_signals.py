#!/usr/bin/env python3
"""
信号分析工具 - 读取和分析JSONL格式的历史交易信号

功能:
1. 加载历史信号数据
2. 统计信号分布（BUY/SELL/HOLD）
3. 分析置信度分布
4. 计算每个币种的信号频率
5. 识别高置信度信号模式
6. 生成详细的分析报告
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, Counter
import pandas as pd
import numpy as np
import argparse
from tabulate import tabulate

class SignalAnalyzer:
    def __init__(self, signal_dir: str = None):
        """初始化信号分析器"""
        if signal_dir is None:
            signal_dir = os.path.expanduser('~/.qlib/signal_logs')

        self.signal_dir = Path(signal_dir)
        if not self.signal_dir.exists():
            print(f"信号目录不存在: {self.signal_dir}")
            sys.exit(1)

        self.signals = []
        self.df = None

    def load_signals(self, days_back: int = 7, specific_date: str = None) -> int:
        """加载JSONL信号文件"""
        files_loaded = 0

        if specific_date:
            # 加载特定日期的信号
            file_path = self.signal_dir / f"signals_{specific_date}.jsonl"
            if file_path.exists():
                self._load_file(file_path)
                files_loaded = 1
        else:
            # 加载最近N天的信号
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)

            for i in range(days_back + 1):
                date = (start_date + timedelta(days=i)).strftime('%Y%m%d')
                file_path = self.signal_dir / f"signals_{date}.jsonl"

                if file_path.exists():
                    self._load_file(file_path)
                    files_loaded += 1

        # 转换为DataFrame
        if self.signals:
            self.df = pd.DataFrame(self.signals)
            # 解析时间戳
            self.df['timestamp'] = pd.to_datetime(self.df['timestamp'])
            if 'logged_at' in self.df.columns:
                self.df['logged_at'] = pd.to_datetime(self.df['logged_at'])

        print(f"加载了 {files_loaded} 个文件，共 {len(self.signals)} 条信号")
        return len(self.signals)

    def _load_file(self, file_path: Path):
        """加载单个JSONL文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        signal = json.loads(line)
                        self.signals.append(signal)
            print(f"  已加载: {file_path.name}")
        except Exception as e:
            print(f"  加载失败 {file_path.name}: {e}")

    def basic_stats(self) -> Dict:
        """计算基本统计信息"""
        if self.df is None or self.df.empty:
            return {}

        stats = {
            'total_signals': len(self.df),
            'unique_symbols': self.df['symbol'].nunique(),
            'date_range': f"{self.df['timestamp'].min()} 到 {self.df['timestamp'].max()}",
            'signal_distribution': self.df['type'].value_counts().to_dict(),
            'avg_confidence': self.df['confidence'].mean(),
            'confidence_std': self.df['confidence'].std(),
        }

        # 按币种统计
        symbol_stats = []
        for symbol in self.df['symbol'].unique():
            symbol_df = self.df[self.df['symbol'] == symbol]
            symbol_stat = {
                'symbol': symbol,
                'total': len(symbol_df),
                'buy': len(symbol_df[symbol_df['type'] == 'long']),
                'sell': len(symbol_df[symbol_df['type'] == 'short']),
                'hold': len(symbol_df[symbol_df['type'] == 'hold']),
                'avg_confidence': symbol_df['confidence'].mean(),
                'max_confidence': symbol_df['confidence'].max(),
            }
            symbol_stats.append(symbol_stat)

        stats['symbol_stats'] = pd.DataFrame(symbol_stats)

        return stats

    def analyze_high_confidence_signals(self, threshold: float = 0.7) -> pd.DataFrame:
        """分析高置信度信号"""
        if self.df is None or self.df.empty:
            return pd.DataFrame()

        high_conf = self.df[self.df['confidence'] >= threshold].copy()

        if high_conf.empty:
            return pd.DataFrame()

        # 按类型和币种分组
        summary = high_conf.groupby(['symbol', 'type']).agg({
            'confidence': ['count', 'mean', 'std'],
            'buy_prob': ['mean', 'std'] if 'buy_prob' in high_conf.columns else [],
            'price': ['mean'] if 'price' in high_conf.columns else []
        }).round(4)

        return summary

    def analyze_signal_patterns(self) -> Dict:
        """分析信号模式"""
        if self.df is None or self.df.empty:
            return {}

        patterns = {}

        # 时间分布（按小时）
        self.df['hour'] = self.df['timestamp'].dt.hour
        hour_dist = self.df.groupby('hour')['type'].value_counts().unstack(fill_value=0)
        patterns['hourly_distribution'] = hour_dist

        # 信号频率（每个币种每天的信号数）
        self.df['date'] = self.df['timestamp'].dt.date
        daily_signals = self.df.groupby(['date', 'symbol']).size().reset_index(name='signals_per_day')
        patterns['avg_daily_signals'] = daily_signals.groupby('symbol')['signals_per_day'].mean().to_dict()

        # 连续信号分析（同一方向连续出现）
        consecutive = []
        for symbol in self.df['symbol'].unique():
            symbol_df = self.df[self.df['symbol'] == symbol].sort_values('timestamp')
            if len(symbol_df) > 1:
                # 计算信号变化
                symbol_df['signal_change'] = (symbol_df['type'] != symbol_df['type'].shift()).cumsum()
                consecutive_groups = symbol_df.groupby(['type', 'signal_change']).size()
                max_consecutive = consecutive_groups.max() if not consecutive_groups.empty else 0
                consecutive.append({
                    'symbol': symbol,
                    'max_consecutive': max_consecutive,
                    'avg_consecutive': consecutive_groups.mean() if not consecutive_groups.empty else 0
                })

        patterns['consecutive_signals'] = pd.DataFrame(consecutive) if consecutive else pd.DataFrame()

        return patterns

    def generate_report(self, output_file: str = None):
        """生成分析报告"""
        print("\n" + "="*80)
        print("                        交易信号分析报告")
        print("="*80)

        # 基本统计
        stats = self.basic_stats()
        if not stats:
            print("\n没有数据可分析")
            return

        print(f"\n📊 基本统计")
        print(f"  • 总信号数: {stats['total_signals']}")
        print(f"  • 币种数量: {stats['unique_symbols']}")
        print(f"  • 时间范围: {stats['date_range']}")
        print(f"  • 平均置信度: {stats['avg_confidence']:.4f} (±{stats['confidence_std']:.4f})")

        print(f"\n📈 信号分布")
        for signal_type, count in stats['signal_distribution'].items():
            percentage = (count / stats['total_signals']) * 100
            print(f"  • {signal_type.upper()}: {count} ({percentage:.1f}%)")

        print(f"\n💰 币种统计")
        symbol_df = stats['symbol_stats']
        symbol_df = symbol_df.sort_values('total', ascending=False)
        print(tabulate(symbol_df, headers='keys', tablefmt='grid', floatfmt='.4f'))

        # 高置信度信号
        high_conf = self.analyze_high_confidence_signals(0.7)
        if not high_conf.empty:
            print(f"\n🎯 高置信度信号 (>0.7)")
            print(tabulate(high_conf, headers='keys', tablefmt='grid', floatfmt='.4f'))

        # 信号模式
        patterns = self.analyze_signal_patterns()

        if 'avg_daily_signals' in patterns:
            print(f"\n📅 平均每日信号数")
            for symbol, avg in patterns['avg_daily_signals'].items():
                print(f"  • {symbol}: {avg:.2f} 信号/天")

        if 'consecutive_signals' in patterns and not patterns['consecutive_signals'].empty:
            print(f"\n🔄 连续信号分析")
            cons_df = patterns['consecutive_signals'].sort_values('max_consecutive', ascending=False)
            print(tabulate(cons_df.head(10), headers='keys', tablefmt='grid', floatfmt='.2f'))

        # 保存到文件
        if output_file:
            self._save_report_to_file(stats, patterns, output_file)
            print(f"\n报告已保存到: {output_file}")

    def _save_report_to_file(self, stats: Dict, patterns: Dict, output_file: str):
        """保存报告到文件"""
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("交易信号分析报告\n")
            f.write("=" * 80 + "\n\n")

            # 基本统计
            f.write("基本统计:\n")
            f.write(f"  总信号数: {stats['total_signals']}\n")
            f.write(f"  币种数量: {stats['unique_symbols']}\n")
            f.write(f"  时间范围: {stats['date_range']}\n")
            f.write(f"  平均置信度: {stats['avg_confidence']:.4f}\n\n")

            # 币种统计表
            f.write("币种统计:\n")
            f.write(stats['symbol_stats'].to_string())
            f.write("\n\n")

            # 添加原始数据导出选项
            if hasattr(self, 'df') and self.df is not None:
                csv_file = output_file.replace('.txt', '.csv')
                self.df.to_csv(csv_file, index=False)
                f.write(f"原始数据已导出到: {csv_file}\n")

    def export_for_backtest(self, output_file: str):
        """导出格式化的信号用于回测"""
        if self.df is None or self.df.empty:
            print("没有数据可导出")
            return

        # 选择回测需要的字段
        backtest_df = self.df[['timestamp', 'symbol', 'type', 'confidence', 'price']].copy()

        # 转换type到标准格式
        type_mapping = {'long': 'BUY', 'short': 'SELL', 'hold': 'HOLD'}
        backtest_df['signal'] = backtest_df['type'].map(type_mapping)

        # 按时间排序
        backtest_df = backtest_df.sort_values('timestamp')

        # 保存为CSV
        backtest_df.to_csv(output_file, index=False)
        print(f"回测数据已导出到: {output_file}")
        print(f"包含 {len(backtest_df)} 条信号记录")


def main():
    parser = argparse.ArgumentParser(description='分析交易信号JSONL日志')
    parser.add_argument('--days', type=int, default=7, help='分析最近N天的数据')
    parser.add_argument('--date', type=str, help='分析特定日期(格式: YYYYMMDD)')
    parser.add_argument('--dir', type=str, help='信号日志目录路径')
    parser.add_argument('--output', type=str, help='保存报告到文件')
    parser.add_argument('--export', type=str, help='导出回测格式数据')
    parser.add_argument('--threshold', type=float, default=0.7, help='高置信度阈值')

    args = parser.parse_args()

    # 创建分析器
    analyzer = SignalAnalyzer(args.dir)

    # 加载数据
    signal_count = analyzer.load_signals(days_back=args.days, specific_date=args.date)

    if signal_count == 0:
        print("没有找到信号数据")
        return

    # 生成报告
    analyzer.generate_report(output_file=args.output)

    # 导出回测数据
    if args.export:
        analyzer.export_for_backtest(args.export)


if __name__ == "__main__":
    main()