

from . import bp
from ...decorators.auth import roles_required
from ...controllers.api_admin.payout import AdminPayoutController

@bp.route("/payout", methods=["POST"])
@roles_required("Super Admin", "Admin", "Junior Admin")
def payout():
    return AdminPayoutController.initiate_payout()

@bp.route("/verify-payout", methods=["POST"])
@roles_required("Super Admin", "Admin", "Junior Admin")
def verify_payout_otp():
    return AdminPayoutController.verify_payout_otp()

