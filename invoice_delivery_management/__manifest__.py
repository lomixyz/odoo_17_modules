{
    'name': 'Invoice Delivery Management',
    'version': '17.0.2.1.1',
    'category': 'Accounting/Accounting',
    'author': 'Allam Bushra',
    'maintainer': 'Allam Bushra',
    'website': 'https://www.linkedin.com/in/lomixyz',
    'summary': 'Save time: link inventory directly to invoices - confirming a '
               'customer invoice automatically deducts its products from stock',
    'description': """
Invoice Delivery Management
===========================
Designed to save time by linking inventory directly to invoices.
When an invoice is confirmed, the quantity of the product or products on
the invoice is deducted from stock automatically.

Key features
------------
* Automatic stock deduction (delivery order) on customer invoice confirmation.
* Credit notes return the products to stock automatically (optional).
* Reset to draft / cancel reverses the stock movement automatically (optional),
  so re-confirming an edited invoice always matches the new quantities.
* Shortage policy: allow negative stock, keep the delivery waiting, or block
  the invoice confirmation.
* Warehouse per invoice (defaults from company settings / user warehouse).
* Unit of measure conversion (e.g. invoice in Dozens, stock in Units).
* Lines coming from Sales Orders are skipped to avoid double deduction.
* Available quantity per invoice line, highlighted in red when insufficient.
* Delivery status on invoices (list, form, filters, group by).
* Protection: only Accounting Managers can delete, cancel or reset to draft
  an invoice with a completed delivery.
* Multi-company and multi-warehouse aware; Arabic translation included.

UPDATE (2.1.0/2.1.1): the Available Qty column on invoice lines now keeps
the figure it had at the time the invoice was last edited as a draft, and
once more right when it was confirmed, instead of showing today's stock
level every time an old invoice is reopened. Note: this only applies going
forward - invoice lines created before this update have no stored
snapshot, so the first time this version computes them (right after the
upgrade) they will take today's stock level as their snapshot, same as
before.
""",
    'depends': ['account', 'stock'],
    'data': [
        'views/account_move_views.xml',
        'views/stock_picking_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
