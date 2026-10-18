import sys, os
sys.path.insert(0, os.path.abspath('.'))

from services.channel_analytics_service import ChannelAnalyticsService

srv = ChannelAnalyticsService(r'e:\TOOL DUNG CODE\bottradecrypto\data\trading_state.db')
lb = srv.get_channel_leaderboard(timeframe='all', bankroll_usd=86.18, margin_per_trade_pct=1.5)

print(f"Total channels in leaderboard: {len(lb.get('channels', []))}")
for ch in lb.get('channels', []):
    perf = ch['performance']
    clean_name = ch['channel_name'].encode('ascii', 'ignore').decode('ascii')
    print(f"Rank {ch['rank']}: {clean_name:25s} ({ch['tier']}) | Total: {ch['total_signals']:3d} | Valid: {ch['validated_signals']:3d} | Rej: {ch['rejected_signals']:3d} | WinRate: {perf['win_rate_pct']:5.1f}% | RejRate: {ch['rejection_rate_pct']:5.1f}% | PnL: ${perf['net_pnl_usd']:6.2f} ({perf['roi_pct']:5.1f}%)")

