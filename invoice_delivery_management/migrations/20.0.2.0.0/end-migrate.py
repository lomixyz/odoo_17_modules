from odoo import SUPERUSER_ID, api

from odoo.addons.invoice_delivery_management.hooks import post_init_hook


def migrate(cr, version):
    """Upgrade from 1.x: hard-link legacy deliveries and protect historical invoices."""
    post_init_hook(api.Environment(cr, SUPERUSER_ID, {}))
