import ConsolidatedBalancePanel from '@/components/ConsolidatedBalancePanel'
import BalanceHistoryPanel from '@/components/BalanceHistoryPanel'

export default function BalancesPanel({ ownerId, onExpired }) {
  return (
    <div className="balance-panels">
      <ConsolidatedBalancePanel ownerId={ownerId} onExpired={onExpired} />
      <BalanceHistoryPanel ownerId={ownerId} onExpired={onExpired} />
    </div>
  )
}
