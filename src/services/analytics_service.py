"""
Analytics Service
Provides calculations and data aggregation for admin dashboard analytics
"""

import logging
from datetime import datetime, timedelta, date
from sqlalchemy import func, desc, and_
from src.models.database import db
from src.models.user import User, UserRole, Club, Video, RecordingSession, Transaction, TransactionStatus
from src.models.analytics import PlatformMetrics, UserEngagement, ClubPerformance, VideoView
import time

logger = logging.getLogger(__name__)


def calculate_growth_percentage(current, previous):
    """
    Calculate percentage growth between two values
    
    Args:
        current: Current period value
        previous: Previous period value
        
    Returns:
        float: Percentage change (positive for growth, negative for decline)
    """
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return ((current - previous) / previous) * 100


def get_daily_active_users(target_date=None):
    """
    Calculate daily active users (DAU) for a specific date
    Users are considered active if they logged in that day
    
    Args:
        target_date: Date to calculate DAU for (defaults to today)
        
    Returns:
        int: Number of unique active users
    """
    if target_date is None:
        target_date = date.today()
        
    # Convert date to datetime range
    start_datetime = datetime.combine(target_date, datetime.min.time())
    end_datetime = datetime.combine(target_date, datetime.max.time())
    
    # Count users who logged in on this date
    dau_count = User.query.filter(
        User.last_login_at >= start_datetime,
        User.last_login_at <= end_datetime,
        User.role != UserRole.SUPER_ADMIN  # Exclude super admins from DAU
    ).count()
    
    return dau_count


def get_system_health_metrics():
    """
    Get real-time system health metrics
    
    Returns:
        dict: System health data including API response time, DB performance, uptime, error rate
    """
    try:
        # Measure database query performance
        start_time = time.time()
        User.query.limit(1).all()
        db_response_time = (time.time() - start_time) * 1000  # Convert to ms
        
        # Simple API response time (this function's execution time)
        api_response_time = db_response_time  # Simplified for now
        
        # Server uptime - calculate based on oldest recording session or user
        oldest_record = User.query.order_by(User.created_at.asc()).first()
        if oldest_record and oldest_record.created_at:
            uptime_seconds = (datetime.utcnow() - oldest_record.created_at).total_seconds()
            uptime_percentage = 99.9  # Simplified - would need actual monitoring data
        else:
            uptime_seconds = 0
            uptime_percentage = 100.0
        
        # Error rate - simplified (would need actual error tracking)
        error_rate = 0.5  # Placeholder - would come from logging/monitoring service
        
        return {
            'api_response_time_ms': round(api_response_time, 2),
            'db_performance_ms': round(db_response_time, 2),
            'server_uptime_percentage': uptime_percentage,
            'error_rate_percentage': error_rate,
            'status': 'healthy' if api_response_time < 500 and error_rate < 5 else 'degraded',
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error calculating system health: {e}")
        return {
            'api_response_time_ms': 0,
            'db_performance_ms': 0,
            'server_uptime_percentage': 0,
            'error_rate_percentage': 100,
            'status': 'error',
            'timestamp': datetime.utcnow().isoformat(),
            'error': str(e)
        }


def get_platform_overview():
    """
    Get platform-wide overview statistics with growth percentages
    
    Returns:
        dict: Platform overview data
    """
    try:
        # Current totals
        total_users = User.query.filter(User.role != UserRole.CLUB).count()
        total_clubs = Club.query.count()
        total_videos = Video.query.count()
        
        # Get yesterday's metrics for comparison
        yesterday = date.today() - timedelta(days=1)
        yesterday_metrics = PlatformMetrics.query.filter_by(date=yesterday).first()
        
        # Calculate growth percentages
        if yesterday_metrics:
            user_growth = calculate_growth_percentage(total_users, yesterday_metrics.total_users)
            club_growth = calculate_growth_percentage(total_clubs, yesterday_metrics.total_clubs)
            
            # Revenue growth (convert from cents to euros)
            today_revenue = 0  # Will be calculated from transactions
            yesterday_revenue = yesterday_metrics.total_revenue_cents / 100
            revenue_growth = calculate_growth_percentage(today_revenue, yesterday_revenue)
        else:
            user_growth = 0
            club_growth = 0
            revenue_growth = 0
        
        # Get monthly revenue (simplified - based on completed transactions)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        monthly_revenue_cents = db.session.query(func.sum(Transaction.amount_cents)).filter(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.created_at >= thirty_days_ago
        ).scalar() or 0
        
        return {
            'total_users': total_users,
            'user_growth_percentage': round(user_growth, 2),
            'total_clubs': total_clubs,
            'club_growth_percentage': round(club_growth, 2),
            'total_videos': total_videos,
            'monthly_revenue_euros': round(monthly_revenue_cents / 100, 2),
            'revenue_growth_percentage': round(revenue_growth, 2),
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting platform overview: {e}")
        return {
            'total_users': 0,
            'user_growth_percentage': 0,
            'total_clubs': 0,
            'club_growth_percentage': 0,
            'total_videos': 0,
            'monthly_revenue_euros': 0,
            'revenue_growth_percentage': 0,
            'error': str(e)
        }


def get_user_growth_data(timeframe='week'):
    """
    Get user growth data over time
    
    Args:
        timeframe: 'week', 'month', or 'year'
        
    Returns:
        dict: User growth data with daily/weekly/monthly breakdown
    """
    try:
        # Determine date range
        if timeframe == 'week':
            start_date = date.today() - timedelta(days=7)
            group_by_format = '%Y-%m-%d'
        elif timeframe == 'month':
            start_date = date.today() - timedelta(days=30)
            group_by_format = '%Y-%m-%d'
        else:  # year
            start_date = date.today() - timedelta(days=365)
            group_by_format = '%Y-%m'
        
        # Query users created in the timeframe
        users_by_date = db.session.query(
            func.date(User.created_at).label('date'),
            func.count(User.id).label('count')
        ).filter(
            User.created_at >= start_date,
            User.role != UserRole.CLUB
        ).group_by(
            func.date(User.created_at)
        ).order_by('date').all()
        
        # Format data for charts
        data_points = [
            {
                'date': str(item.date),
                'new_users': item.count
            }
            for item in users_by_date
        ]
        
        # Calculate total new users in period
        total_new_users = sum(point['new_users'] for point in data_points)
        
        return {
            'timeframe': timeframe,
            'data': data_points,
            'total_new_users': total_new_users,
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting user growth data: {e}")
        return {
            'timeframe': timeframe,
            'data': [],
            'total_new_users': 0,
            'error': str(e)
        }


def get_club_adoption_data(timeframe='month'):
    """
    Get club adoption data over time
    
    Args:
        timeframe: 'week', 'month', or 'year'
        
    Returns:
        dict: Club adoption data with breakdown
    """
    try:
        # Determine date range
        if timeframe == 'week':
            start_date = date.today() - timedelta(days=7)
        elif timeframe == 'month':
            start_date = date.today() - timedelta(days=30)
        else:  # year
            start_date = date.today() - timedelta(days=365)
        
        # Query clubs created in the timeframe
        clubs_by_date = db.session.query(
            func.date(Club.created_at).label('date'),
            func.count(Club.id).label('count')
        ).filter(
            Club.created_at >= start_date
        ).group_by(
            func.date(Club.created_at)
        ).order_by('date').all()
        
        # Format data for charts
        data_points = [
            {
                'date': str(item.date),
                'new_clubs': item.count
            }
            for item in clubs_by_date
        ]
        
        total_new_clubs = sum(point['new_clubs'] for point in data_points)
        
        return {
            'timeframe': timeframe,
            'data': data_points,
            'total_new_clubs': total_new_clubs,
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting club adoption data: {e}")
        return {
            'timeframe': timeframe,
            'data': [],
            'total_new_clubs': 0,
            'error': str(e)
        }


def get_revenue_growth_data(timeframe='month'):
    """
    Get revenue growth data over time
    
    Args:
        timeframe: 'week', 'month', or 'year'
        
    Returns:
        dict: Revenue data with breakdown
    """
    try:
        # Determine date range
        if timeframe == 'week':
            start_date = datetime.utcnow() - timedelta(days=7)
        elif timeframe == 'month':
            start_date = datetime.utcnow() - timedelta(days=30)
        else:  # year
            start_date = datetime.utcnow() - timedelta(days=365)
        
        # Query completed transactions in the timeframe
        revenue_by_date = db.session.query(
            func.date(Transaction.completed_at).label('date'),
            func.sum(Transaction.amount_cents).label('total_cents')
        ).filter(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.completed_at >= start_date
        ).group_by(
            func.date(Transaction.completed_at)
        ).order_by('date').all()
        
        # Format data for charts
        data_points = [
            {
                'date': str(item.date) if item.date else 'unknown',
                'revenue_euros': round((item.total_cents or 0) / 100, 2)
            }
            for item in revenue_by_date
        ]
        
        total_revenue = sum(point['revenue_euros'] for point in data_points)
        
        return {
            'timeframe': timeframe,
            'data': data_points,
            'total_revenue_euros': round(total_revenue, 2),
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting revenue growth data: {e}")
        return {
            'timeframe': timeframe,
            'data': [],
            'total_revenue_euros': 0,
            'error': str(e)
        }


def get_user_engagement_metrics():
    """
    Get user engagement metrics (DAU, recording sessions, video views)
    
    Returns:
        dict: Engagement metrics
    """
    try:
        # Daily Active Users (today)
        today = date.today()
        dau = get_daily_active_users(today)
        
        # Recording sessions today
        start_of_day = datetime.combine(today, datetime.min.time())
        end_of_day = datetime.combine(today, datetime.max.time())
        
        sessions_today = RecordingSession.query.filter(
            RecordingSession.start_time >= start_of_day,
            RecordingSession.start_time <= end_of_day
        ).count()
        
        # Recording sessions this week
        week_ago = datetime.utcnow() - timedelta(days=7)
        sessions_this_week = RecordingSession.query.filter(
            RecordingSession.start_time >= week_ago
        ).count()
        
        # Total video views (if tracking exists)
        total_video_views = VideoView.query.count()
        
        # Court bookings (derived from recording sessions - each session is a booking)
        court_bookings = sessions_today
        
        return {
            'daily_active_users': dau,
            'recording_sessions_today': sessions_today,
            'recording_sessions_this_week': sessions_this_week,
            'court_bookings_today': court_bookings,
            'total_video_views': total_video_views,
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting user engagement metrics: {e}")
        return {
            'daily_active_users': 0,
            'recording_sessions_today': 0,
            'recording_sessions_this_week': 0,
            'court_bookings_today': 0,
            'total_video_views': 0,
            'error': str(e)
        }


def get_top_performing_clubs(limit=10):
    """
    Get top performing clubs by revenue and engagement
    
    Args:
        limit: Number of top clubs to return
        
    Returns:
        list: Top performing clubs data
    """
    try:
        # Get all clubs with their metrics
        clubs = Club.query.all()
        club_data = []
        
        for club in clubs:
            # Count videos for this club
            video_count = Video.query.join(Video.court).filter(
                Video.court.has(club_id=club.id)
            ).count()
            
            # Count active users (users who have videos at this club)
            active_users = db.session.query(func.count(func.distinct(Video.user_id))).join(
                Video.court
            ).filter(Video.court.has(club_id=club.id)).scalar() or 0
            
            # Calculate revenue (simplified - based on credits used)
            # In a real system, this would come from ClubPerformance table
            revenue_euros = video_count * 1.0  # Placeholder: assume 1€ per video
            
            # Calculate engagement score (weighted formula)
            engagement_score = (video_count * 0.4) + (active_users * 0.6)
            
            club_data.append({
                'club_id': club.id,
                'club_name': club.name,
                'total_videos': video_count,
                'total_revenue_euros': round(revenue_euros, 2),
                'active_users': active_users,
                'engagement_score': round(engagement_score, 2)
            })
        
        # Sort by engagement score (or revenue) and return top N
        club_data.sort(key=lambda x: x['engagement_score'], reverse=True)
        
        return {
            'clubs': club_data[:limit],
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting top performing clubs: {e}")
        return {
            'clubs': [],
            'error': str(e)
        }


def get_financial_overview():
    """
    Get financial overview for the current month
    
    Returns:
        dict: Financial summary
    """
    try:
        # Get current month date range
        today = date.today()
        first_day_of_month = date(today.year, today.month, 1)
        first_day_datetime = datetime.combine(first_day_of_month, datetime.min.time())
        
        # Total revenue this month (completed transactions)
        monthly_revenue_cents = db.session.query(func.sum(Transaction.amount_cents)).filter(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.completed_at >= first_day_datetime
        ).scalar() or 0
        
        total_revenue_euros = round(monthly_revenue_cents / 100, 2)
        
        # Commission earned (placeholder - would need commission rate from config)
        # Using 20% as default
        commission_rate = 0.20
        commission_earned_euros = round(total_revenue_euros * commission_rate, 2)
        
        # Active subscriptions (users with credits > 0)
        active_subscriptions = User.query.filter(
            User.credits_balance > 0,
            User.role != UserRole.SUPER_ADMIN
        ).count()
        
        # Pending payouts (placeholder - would come from a payouts table)
        pending_payouts_euros = 0.0
        
        return {
            'total_revenue_euros': total_revenue_euros,
            'commission_earned_euros': commission_earned_euros,
            'commission_rate_percentage': commission_rate * 100,
            'active_subscriptions': active_subscriptions,
            'pending_payouts_euros': pending_payouts_euros,
            'month': today.strftime('%B %Y'),
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting financial overview: {e}")
        return {
            'total_revenue_euros': 0,
            'commission_earned_euros': 0,
            'commission_rate_percentage': 0,
            'active_subscriptions': 0,
            'pending_payouts_euros': 0,
            'error': str(e)
        }


def aggregate_daily_metrics(target_date=None):
    """
    Background job to aggregate and store daily metrics in PlatformMetrics table
    Should be run once per day (e.g., via cron or Celery task)
    
    Args:
        target_date: Date to aggregate metrics for (defaults to yesterday)
        
    Returns:
        bool: Success status
    """
    try:
        if target_date is None:
            target_date = date.today() - timedelta(days=1)  # Yesterday
        
        # Check if metrics already exist for this date
        existing_metrics = PlatformMetrics.query.filter_by(date=target_date).first()
        
        # Calculate all metrics for the date
        start_datetime = datetime.combine(target_date, datetime.min.time())
        end_datetime = datetime.combine(target_date, datetime.max.time())
        
        # User metrics
        total_users = User.query.filter(User.role != UserRole.CLUB).count()
        new_users_today = User.query.filter(
            User.created_at >= start_datetime,
            User.created_at <= end_datetime,
            User.role != UserRole.CLUB
        ).count()
        active_users_today = get_daily_active_users(target_date)
        
        # Club metrics
        total_clubs = Club.query.count()
        new_clubs_today = Club.query.filter(
            Club.created_at >= start_datetime,
            Club.created_at <= end_datetime
        ).count()
        
        # Video metrics
        total_videos = Video.query.count()
        new_videos_today = Video.query.filter(
            Video.created_at >= start_datetime,
            Video.created_at <= end_datetime
        ).count()
        
        # Recording metrics
        recording_sessions_today = RecordingSession.query.filter(
            RecordingSession.start_time >= start_datetime,
            RecordingSession.start_time <= end_datetime
        ).count()
        
        # Financial metrics
        revenue_today_cents = db.session.query(func.sum(Transaction.amount_cents)).filter(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.completed_at >= start_datetime,
            Transaction.completed_at <= end_datetime
        ).scalar() or 0
        
        total_revenue_cents = db.session.query(func.sum(Transaction.amount_cents)).filter(
            Transaction.status == TransactionStatus.COMPLETED
        ).scalar() or 0
        
        if existing_metrics:
            # Update existing metrics
            existing_metrics.total_users = total_users
            existing_metrics.new_users_today = new_users_today
            existing_metrics.active_users_today = active_users_today
            existing_metrics.total_clubs = total_clubs
            existing_metrics.new_clubs_today = new_clubs_today
            existing_metrics.total_videos = total_videos
            existing_metrics.new_videos_today = new_videos_today
            existing_metrics.recording_sessions_today = recording_sessions_today
            existing_metrics.revenue_today_cents = revenue_today_cents
            existing_metrics.total_revenue_cents = total_revenue_cents
            existing_metrics.updated_at = datetime.utcnow()
        else:
            # Create new metrics record
            metrics = PlatformMetrics(
                date=target_date,
                total_users=total_users,
                new_users_today=new_users_today,
                active_users_today=active_users_today,
                total_clubs=total_clubs,
                new_clubs_today=new_clubs_today,
                total_videos=total_videos,
                new_videos_today=new_videos_today,
                recording_sessions_today=recording_sessions_today,
                revenue_today_cents=revenue_today_cents,
                total_revenue_cents=total_revenue_cents
            )
            db.session.add(metrics)
        
        db.session.commit()
        logger.info(f"Successfully aggregated metrics for {target_date}")
        return True
        
    except Exception as e:
        logger.error(f"Error aggregating daily metrics: {e}")
        db.session.rollback()
        return False
