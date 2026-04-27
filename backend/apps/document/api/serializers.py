from rest_framework import serializers
from django.contrib.auth import get_user_model
from apps.document.models import SmartChunk, Document, DocumentShare, DocumentShareRole, Category
from apps.document.category_utils import category_ancestor_path, resolve_write_category
from apps.user.models import UserRole

User = get_user_model()


def _can_manage_public_documents(user) -> bool:
    if not user:
        return False
    return bool(user.is_superuser or getattr(user, "role", None) == UserRole.ADMIN)

class SmartChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SmartChunk
        fields = [
            'id',
            'content',
            'chunk_index',
            'document_id',
            'token_count',
            'embedding',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at', "content_norm"]


class DocumentCreateSerializer(serializers.ModelSerializer):
    file = serializers.FileField(required=True, allow_null=False, allow_empty_file=False)
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    category = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    category_slug = serializers.SlugField(
        required=False, allow_blank=True, write_only=True,
        help_text="Preferred: assign document to this category by slug (owner must match).",
    )
    description = serializers.CharField(required=False, allow_blank=True)
    is_public = serializers.BooleanField(required=False, default=False)
    project_slug = serializers.SlugField(
        write_only=True, required=False, allow_blank=True,
    )

    class Meta:
        model = Document
        fields = [
            'file',
            'name',
            'category',
            'category_slug',
            'description',
            'is_public',
            'project_slug',
        ]

    def validate_file(self, value):
        if not value:
            raise serializers.ValidationError("File is required.")
        return value

    def validate_project_slug(self, value):
        if not value:
            return value
        from apps.project.models import Project
        try:
            project = Project.objects.get(slug=value)
        except Project.DoesNotExist:
            raise serializers.ValidationError("Project not found.")
        request = self.context.get('request')
        if request and not project.can_edit(request.user):
            raise serializers.ValidationError(
                "You do not have permission to add documents to this project."
            )
        self._project = project
        return value

    def validate_is_public(self, value):
        # Public visibility can only be changed after upload in document edit flows.
        if value:
            raise serializers.ValidationError(
                "is_public can only be set on already uploaded documents."
            )
        return value

    def create(self, validated_data):
        validated_data.pop('project_slug', None)
        request = self.context.get('request')
        user = request.user
        is_staff = user.is_staff
        category_slug = validated_data.pop('category_slug', None)
        category_text = validated_data.pop('category', None)
        if category_slug and str(category_slug).strip():
            try:
                cat, cat_str = resolve_write_category(
                    user,
                    category_slug=category_slug,
                    is_staff=is_staff,
                )
            except ValueError as e:
                if str(e) == "category_not_found":
                    raise serializers.ValidationError(
                        {"category_slug": "Category not found."},
                    ) from e
                raise serializers.ValidationError(
                    {"category_slug": "You do not have permission to use this category."},
                ) from e
            validated_data['category_ref'] = cat
            validated_data['category'] = cat_str
        else:
            try:
                cat, cat_str = resolve_write_category(
                    user,
                    category_name=category_text,
                    is_staff=is_staff,
                )
            except ValueError as e:
                if str(e) == "category_not_found":
                    raise serializers.ValidationError(
                        {"category": "Category not found."},
                    ) from e
                raise serializers.ValidationError(
                    {"category": "You do not have permission to use this category."},
                ) from e
            validated_data['category_ref'] = cat
            validated_data['category'] = cat_str
        return super().create(validated_data)


class DocumentBulkPublicSerializer(serializers.Serializer):
    """Superusers only: bulk set is_public (public library visibility)."""

    slugs = serializers.ListField(
        child=serializers.SlugField(),
        min_length=1,
        max_length=200,
    )
    is_public = serializers.BooleanField()


class DocumentBulkCreateSerializer(serializers.Serializer):
    files = serializers.ListField(
        child=serializers.FileField(required=True, allow_null=False, allow_empty_file=False),
        required=True,
        min_length=1,
        max_length=100,
    )
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    category = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    category_slug = serializers.SlugField(required=False, allow_blank=True, write_only=True)
    description = serializers.CharField(required=False, allow_blank=True)
    is_public = serializers.BooleanField(required=False, default=False)
    project_slug = serializers.SlugField(
        write_only=True, required=False, allow_blank=True,
    )

    def validate_files(self, value):
        if not value or len(value) == 0:
            raise serializers.ValidationError("At least one file is required.")
        for file in value:
            if not file:
                raise serializers.ValidationError("All files must be provided and not empty.")
            if file.size == 0:
                raise serializers.ValidationError("Files cannot be empty.")
        return value

    def validate_project_slug(self, value):
        if not value:
            return value
        from apps.project.models import Project
        try:
            project = Project.objects.get(slug=value)
        except Project.DoesNotExist:
            raise serializers.ValidationError("Project not found.")
        request = self.context.get('request')
        if request and not project.can_edit(request.user):
            raise serializers.ValidationError(
                "You do not have permission to add documents to this project."
            )
        self._project = project
        return value

    def validate_is_public(self, value):
        # Public visibility can only be changed after upload in document edit flows.
        if value:
            raise serializers.ValidationError(
                "is_public can only be set on already uploaded documents."
            )
        return value

class DocumentSerializer(serializers.ModelSerializer):
    """Serializer for listing documents - read-only fields"""
    is_public = serializers.BooleanField(read_only=True)
    is_owner = serializers.SerializerMethodField()
    owner_email = serializers.EmailField(source='owner.email', read_only=True)
    category_slug = serializers.SerializerMethodField()
    category_path = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            'id',
            'slug',
            'name',
            'category',
            'category_slug',
            'category_path',
            'description',
            'file',
            'is_public',
            'is_owner',
            'owner_email',
            'created_at',
            'chunking_status',
            'chunking_done',
            'last_error',
        ]
        read_only_fields = [
            'id',
            'slug',
            'created_at',
            'chunking_status',
            'chunking_done',
            'last_error',
            'is_public',
            'owner',
            'name',
            'category',
            'description',
        ]
    
    def get_is_owner(self, obj):
        """Indica si el usuario actual es el propietario del documento"""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            return obj.owner == request.user
        return False

    def get_category_slug(self, obj):
        if obj.category_ref_id and obj.category_ref:
            return obj.category_ref.slug
        return None

    def get_category_path(self, obj):
        if not obj.category_ref_id:
            return []
        # May be lazy; ensure ref is present
        ref = obj.category_ref if obj.category_ref_id else None
        if not ref:
            return []
        return [{"name": n, "slug": s} for n, s in category_ancestor_path(ref)]


class DocumentDetailSerializer(serializers.ModelSerializer):
    """Serializer for retrieving a single document with all fields"""
    owner_email = serializers.EmailField(source='owner.email', read_only=True)
    category_slug = serializers.SerializerMethodField()
    category_path = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            'id',
            'slug',
            'name',
            'category',
            'category_slug',
            'category_path',
            'description',
            'file',
            'created_at',
            'chunking_status',
            'chunking_done',
            'is_public',
            'owner_email',
        ]
        read_only_fields = [
            'id',
            'slug',
            'created_at',
            'chunking_status',
            'chunking_done',
            'owner_email',
        ]

    def get_category_slug(self, obj):
        if obj.category_ref_id and obj.category_ref:
            return obj.category_ref.slug
        return None

    def get_category_path(self, obj):
        if not obj.category_ref_id:
            return []
        ref = obj.category_ref if obj.category_ref_id else None
        if not ref:
            return []
        return [{"name": n, "slug": s} for n, s in category_ancestor_path(ref)]


class DocumentUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating document metadata"""
    is_public = serializers.BooleanField(required=False)
    category_slug = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, write_only=True,
    )

    class Meta:
        model = Document
        fields = [
            'name',
            'category',
            'category_slug',
            'description',
            'is_public',
        ]
    
    def validate_is_public(self, value):
        """Only superadmins and admin users can modify is_public field."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            if not _can_manage_public_documents(request.user):
                raise serializers.ValidationError(
                    "Only superadmins and admin users can modify the is_public field."
                )
        return value
    
    def update(self, instance, validated_data):
        """Update document, but restrict is_public to superadmins/admin users."""
        request = self.context.get('request')
        user = request.user if request and hasattr(request, "user") else None
        is_staff = user.is_staff if user else False

        category_changed = False
        new_ref = None
        new_cat = None

        if "category_slug" in validated_data:
            category_changed = True
            validated_data.pop("category", None)
            slug_val = validated_data.pop("category_slug")
            if slug_val is None or (isinstance(slug_val, str) and not str(slug_val).strip()):
                new_ref, new_cat = None, None
            else:
                try:
                    cat, cat_str = resolve_write_category(
                        user,
                        category_slug=str(slug_val).strip(),
                        is_staff=is_staff,
                    )
                except ValueError as e:
                    if str(e) == "category_not_found":
                        raise serializers.ValidationError(
                            {"category_slug": "Category not found."},
                        ) from e
                    raise serializers.ValidationError(
                        {"category_slug": "You do not have permission to use this category."},
                    ) from e
                new_ref, new_cat = cat, cat_str
        elif "category" in validated_data:
            category_changed = True
            ctext = validated_data.pop("category", None)
            if ctext is None or (isinstance(ctext, str) and not str(ctext).strip()):
                new_ref, new_cat = None, None
            else:
                try:
                    cat, cat_str = resolve_write_category(
                        user,
                        category_name=str(ctext).strip(),
                        is_staff=is_staff,
                    )
                except ValueError as e:
                    if str(e) == "category_not_found":
                        raise serializers.ValidationError(
                            {"category": "Category not found."},
                        ) from e
                    raise serializers.ValidationError(
                        {"category": "You do not have permission to use this category."},
                    ) from e
                new_ref, new_cat = cat, cat_str

        # Remove is_public from validated_data if user is not superuser
        if request and hasattr(request, 'user'):
            if not _can_manage_public_documents(request.user) and 'is_public' in validated_data:
                validated_data.pop('is_public')

        instance = super().update(instance, validated_data)
        if category_changed:
            instance.category_ref = new_ref
            instance.category = new_cat
            instance.save(update_fields=["category_ref", "category"])
        return instance


class DocumentShareSerializer(serializers.ModelSerializer):
    """Serializer for reading document shares"""
    user_email = serializers.EmailField(source="user.email", read_only=True)
    
    class Meta:
        model = DocumentShare
        fields = ("id", "user", "user_email", "role", "created_at")
        read_only_fields = ("id", "user_email", "created_at")


class DocumentShareWriteSerializer(serializers.Serializer):
    """Serializer for creating/updating document shares"""
    user_email = serializers.EmailField()
    role = serializers.ChoiceField(choices=DocumentShareRole.choices)
    
    def validate(self, attrs):
        """Valida el email y obtiene el usuario"""
        email = attrs.get('user_email')
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError({
                'user_email': f"No existe un usuario con el email: {email}"
            })
        
        document = self.context.get("document")
        if document and document.owner == user:
            raise serializers.ValidationError({
                'user_email': "El propietario del documento no puede ser compartido."
            })
        
        attrs['user'] = user
        return attrs


class CategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = (
            'id', 'slug', 'name', 'parent', 'children',
            'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'slug', 'created_at', 'updated_at')

    def get_children(self, obj):
        qs = obj.children.all()
        if not qs.exists():
            return []
        return CategorySerializer(qs, many=True).data


class CategoryWriteSerializer(serializers.ModelSerializer):
    parent_slug = serializers.SlugField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Category
        fields = ('name', 'parent_slug')

    def validate_parent_slug(self, value):
        if not value:
            return value
        try:
            parent = Category.objects.get(slug=value)
        except Category.DoesNotExist:
            raise serializers.ValidationError("Parent category not found.")
        request = self.context.get('request')
        if request and parent.owner != request.user and not request.user.is_staff:
            raise serializers.ValidationError("You do not own this parent category.")
        self._parent = parent
        return value

    def create(self, validated_data):
        validated_data.pop('parent_slug', None)
        parent = getattr(self, '_parent', None)
        if parent:
            validated_data['parent'] = parent
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('parent_slug', None)
        parent = getattr(self, '_parent', None)
        if parent:
            validated_data['parent'] = parent
        return super().update(instance, validated_data)