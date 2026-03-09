from flask import Blueprint, request, jsonify, session
from datetime import datetime
from ..services.recovery_service import recovery_service
from ..models.recovery import RecoveryRequestType, VideoRecoveryRequest
from ..models.user import UserRole, User
from ..utils.jwt_helpers import get_current_user_from_token

recovery_bp = Blueprint('recovery', __name__, url_prefix='/api/recovery')

def get_current_user():
    # Try session first
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    
    # Try token
    return get_current_user_from_token()

@recovery_bp.route('/report', methods=['POST'])
def report_missing_video():
    """
    Manually report a missing video to trigger SD card recovery.
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    
    court_id = data.get('court_id')
    match_start = data.get('match_start') # ISO format
    match_end = data.get('match_end')   # ISO format
    description = data.get('description', '')
    
    if not all([court_id, match_start, match_end]):
        return jsonify({'error': 'Missing required fields'}), 400
        
    try:
        start_dt = datetime.fromisoformat(match_start.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(match_end.replace('Z', '+00:00'))
        
        # Create request
        req = recovery_service.create_request(
            court_id=court_id,
            start_time=start_dt,
            end_time=end_dt,
            user_id=current_user.id,
            request_type=RecoveryRequestType.MANUAL
        )
        
        # Trigger processing immediately? Or let Celery handle it?
        # For now, let's trigger it directly for immediate feedback in testing
        # In prod, this should definitely be asynchronous
        try:
             # Just call the service method directly for now
             # Ideally: recovery_task.delay(req.id)
            recovery_service.process_request(req)
        except Exception as e:
            # Even if immediate processing fails, the request is saved
            pass
            
        return jsonify({
            'message': 'Recovery request created',
            'request_id': req.id,
            'status': req.status.value
        }), 201
        
    except ValueError as e:
        return jsonify({'error': f'Invalid date format: {e}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@recovery_bp.route('/requests', methods=['GET'])
def get_recovery_requests():
    """Get list of recovery requests (Admin only)"""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Unauthorized'}), 401

    if current_user.role != UserRole.SUPER_ADMIN:
        return jsonify({'error': 'Unauthorized'}), 403
        
    requests = VideoRecoveryRequest.query.order_by(VideoRecoveryRequest.created_at.desc()).limit(50).all()
    return jsonify({'requests': [r.to_dict() for r in requests]}), 200
