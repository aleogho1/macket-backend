"""
@author: Emmanuel Olowu
@link: https://github.com/zeddyemy
@package: Trendit³
"""

class TransactionMissingError(Exception):
    """Exception raised when a transaction isn't found."""

    def __init__(self, message="Transaction not found", status_code=404):
        super().__init__(message)
        self.status_code = status_code
        self.message = message

class CreditWalletError(Exception):
    """Exception raised when a crediting user's waller."""

    def __init__(self, message="Error crediting wallet.", status_code=500):
        super().__init__(message)
        self.status_code = status_code
        self.message = message

class SignatureError(Exception):
    """Exception raised when a crediting user's waller."""

    def __init__(self, message="Invalid Signature", status_code=500):
        super().__init__(message)
        self.status_code = status_code
        self.message = message

class FlutterwaveError(Exception):
    """Exception raised when a flutterwave request fails."""

    def __init__(self, message="Flutterwave error: ", status_code=500):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
