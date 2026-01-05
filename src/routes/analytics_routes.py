"""
Analytics Routes
API endpoints for admin dashboard analytics
All routes require super admin authentication
"""

import logging
from flask import Blueprint, jsonify, request, session
from functools import wraps
from src.models.user import User, UserRole
from src.services import analytics_service

logger = logging.getLogger(__name__)

analytics_bp = Blueprint('analytics', __name__)


def require_super_admin(f):
    """Decorator to require super admin role (session-based auth)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            user_id = session.get('user_id')
            
            if not user_id:
                logger.warning(f"Unauthorized analytics access attempt - no session")
                return jsonify({'error': 'Authentication required'}), 401
            
            user = User.query.get(user_id)
            
            if not user or user.role != UserRole.SUPER_ADMIN:
                logger.warning(f"Unauthorized analytics access attempt by user {user_id}")
                return jsonify({'error': 'Super admin access required'}), 403
                
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in super admin check: {e}")
            return jsonify({'error': 'Authentication error'}), 500
    
    return decorated_function


@analytics_bp.route('/system-health', methods=['GET'])
@require_super_admin
def get_system_health():
    """
    Get real-time system health metrics
    
    Returns:
        JSON: System health data including API response time, DB performance, uptime, error rate
    """
    try:
        health_data = analytics_service.get_system_health_metrics()
        return jsonify(health_data), 200
    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        return jsonify({'error': 'Failed to retrieve system health metrics'}), 500


@analytics_bp.route('/platform-overview', methods=['GET'])
@require_super_admin
def get_platform_overview():
    """
    Get platform-wide overview statistics with growth percentages
    
    Returns:
        JSON: Platform overview data (users, clubs, revenue with growth %)
    """
    try:
        overview_data = analytics_service.get_platform_overview()
        return jsonify(overview_data), 200
    except Exception as e:
        logger.error(f"Error getting platform overview: {e}")
        return jsonify({'error': 'Failed to retrieve platform overview'}), 500


@analytics_bp.route('/user-growth', methods=['GET'])
@require_super_admin
def get_user_growth():
    """
    Get user growth data over time
    
    Query Parameters:
        timeframe (str): 'week', 'month', or 'year' (default: 'week')
    
    Returns:
        JSON: User growth data with daily/weekly/monthly breakdown
    """
    try:
        timeframe = request.args.get('timeframe', 'week')
        
        if timeframe not in ['week', 'month', 'year']:
            return jsonify({'error': 'Invalid timeframe. Use week, month, or year'}), 400
        
        growth_data = analytics_service.get_user_growth_data(timeframe)
        return jsonify(growth_data), 200
    except Exception as e:
        logger.error(f"Error getting user growth data: {e}")
        return jsonify({'error': 'Failed to retrieve user growth data'}), 500


@analytics_bp.route('/club-adoption', methods=['GET'])
@require_super_admin
def get_club_adoption():
    """
    Get club adoption data over time
    
    Query Parameters:
        timeframe (str): 'week', 'month', or 'year' (default: 'month')
    
    Returns:
        JSON: Club adoption data with breakdown
    """
    try:
        timeframe = request.args.get('timeframe', 'month')
        
        if timeframe not in ['week', 'month', 'year']:
            return jsonify({'error': 'Invalid timeframe. Use week, month, or year'}), 400
        
        adoption_data = analytics_service.get_club_adoption_data(timeframe)
        return jsonify(adoption_data), 200
    except Exception as e:
        logger.error(f"Error getting club adoption data: {e}")
        return jsonify({'error': 'Failed to retrieve club adoption data'}), 500


@analytics_bp.route('/revenue-growth', methods=['GET'])
@require_super_admin
def get_revenue_growth():
    """
    Get revenue growth data over time
    
    Query Parameters:
        timeframe (str): 'week', 'month', or 'year' (default: 'month')
    
    Returns:
        JSON: Revenue data with breakdown
    """
    try:
        timeframe = request.args.get('timeframe', 'month')
        
        if timeframe not in ['week', 'month', 'year']:
            return jsonify({'error': 'Invalid timeframe. Use week, month, or year'}), 400
        
        revenue_data = analytics_service.get_revenue_growth_data(timeframe)
        return jsonify(revenue_data), 200
    except Exception as e:
        logger.error(f"Error getting revenue growth data: {e}")
        return jsonify({'error': 'Failed to retrieve revenue growth data'}), 500


@analytics_bp.route('/user-engagement', methods=['GET'])
@require_super_admin
def get_user_engagement():
    """
    Get user engagement metrics (DAU, recording sessions, video views)
    
    Returns:
        JSON: Engagement metrics
    """
    try:
        engagement_data = analytics_service.get_user_engagement_metrics()
        return jsonify(engagement_data), 200
    except Exception as e:
        logger.error(f"Error getting user engagement metrics: {e}")
        return jsonify({'error': 'Failed to retrieve user engagement metrics'}), 500


@analytics_bp.route('/top-clubs', methods=['GET'])
@require_super_admin
def get_top_clubs():
    """
    Get top performing clubs by revenue and engagement
    
    Query Parameters:
        limit (int): Number of top clubs to return (default: 10, max: 50)
    
    Returns:
        JSON: Top performing clubs data
    """
    try:
        limit = request.args.get('limit', 10, type=int)
        
        # Validate limit
        if limit < 1:
            limit = 10
        elif limit > 50:
            limit = 50
        
        clubs_data = analytics_service.get_top_performing_clubs(limit)
        return jsonify(clubs_data), 200
    except Exception as e:
        logger.error(f"Error getting top performing clubs: {e}")
        return jsonify({'error': 'Failed to retrieve top clubs data'}), 500


@analytics_bp.route('/financial-overview', methods=['GET'])
@require_super_admin
def get_financial_overview():
    """
    Get financial overview for the current month
    
    Returns:
        JSON: Financial summary (revenue, commission, subscriptions, payouts)
    """
    try:
        financial_data = analytics_service.get_financial_overview()
        return jsonify(financial_data), 200
    except Exception as e:
        logger.error(f"Error getting financial overview: {e}")
        return jsonify({'error': 'Failed to retrieve financial overview'}), 500


# Background job endpoint (can be called by cron or Celery)
@analytics_bp.route('/aggregate-metrics', methods=['POST'])
@require_super_admin
def trigger_metrics_aggregation():
    """
    Manually trigger daily metrics aggregation
    Normally this would be run by a scheduled task
    
    Returns:
        JSON: Success status
    """
    try:
        from datetime import date, timedelta
        
        # Optionally accept a date parameter
        target_date_str = request.json.get('date') if request.json else None
        
        if target_date_str:
            from datetime import datetime
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today() - timedelta(days=1)  # Yesterday by default
        
        success = analytics_service.aggregate_daily_metrics(target_date)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Metrics aggregated for {target_date}',
                'date': str(target_date)
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to aggregate metrics',
                'date': str(target_date)
            }), 500
            
    except Exception as e:
        logger.error(f"Error triggering metrics aggregation: {e}")
        return jsonify({'error': 'Failed to trigger metrics aggregation'}), 500
