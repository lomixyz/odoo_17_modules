{
    'name': 'Invoice Delivery Management',
    'version': '1.0',
    'category': 'Accounting',
    'author': 'Allam Bushra',
    'summary': 'Create delivery orders directly from invoices',
    'depends': ['account', 'stock'],
    'data': [
        'views/account_move_views.xml',
    ],
    'installable': True,
    'application': True,
}
