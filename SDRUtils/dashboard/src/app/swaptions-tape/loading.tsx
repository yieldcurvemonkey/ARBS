// Route-specific loading state for the swaptions tape page.
import { Spinner } from '@/components/ui';

export default function SwaptionsTapeLoading() {
  return (
    <div className="flex items-center justify-center py-20">
      <Spinner size="lg" variant="white" />
    </div>
  );
}
