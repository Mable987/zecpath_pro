from rest_framework.pagination import CursorPagination
 
 
class JobFeedCursorPagination(CursorPagination):
    page_size = 10
    ordering = "-posted_at"  
    cursor_query_param = "cursor"