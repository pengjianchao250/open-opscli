"""Amazon Listing Intelligence 服务模块。"""

from opscli.amazon_listing_intelligence.domain.models import (
    ListingIntelligenceRequest,
)
from opscli.amazon_listing_intelligence.services.manager import (
    AmazonListingIntelligenceManager,
)

__all__ = ["AmazonListingIntelligenceManager", "ListingIntelligenceRequest"]
