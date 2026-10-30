from django.urls import path

from . import views


app_name = 'reports'

urlpatterns = [
    path('', views.hub, name='hub'),
    path('stock-valuation/', views.stock_valuation, name='stock_valuation'),
    path('stock-movements/', views.stock_movement_report, name='stock_movement_report'),
    path('low-stock/', views.low_stock_report, name='low_stock_report'),
    path('supplier-stock/', views.supplier_stock_report, name='supplier_stock_report'),
]
