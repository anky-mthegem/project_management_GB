// Organization Chart & Collapsible Tree View Controller (MS Teams / Workday Style)
// Supporting 3-Tier Operational Hierarchy: General Manager (GM) -> Manager (MGR) -> Team Member (TM)

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

window.teamManagerApp = function() {
    return {
        activeTab: 'org-chart', // 'org-chart' | 'tree' | 'directory'
        searchQuery: '',
        selectedDepartmentFilter: '',
        isLoading: true,
        
        // Data sources
        hierarchyData: { departments: [], standalone_teams: [] },
        orgChartNodes: [],
        orgTrees: [], // List of root trees (supports multi-lead / multi-department)
        unassignedUsers: [],
        
        // Org Chart Canvas Controls
        zoomLevel: 1.0,
        collapsedNodes: {},
        selectedNode: null,
        
        // Modals
        showAddTeamModal: false,
        showAddDeptModal: false,
        showAssignMemberModal: false,
        showReportingModal: false,
        
        reportingForm: {
            user_id: null,
            user_name: '',
            role_code: '',
            current_manager_id: null,
            new_manager_id: null
        },
        
        toastMessage: '',
        toastType: 'info',
        showToastNotification: false,

        async init() {
            await this.loadAllData();
            if (window.lucide) lucide.createIcons();
            
            this.$watch('activeTab', () => {
                if (window.lucide) setTimeout(lucide.createIcons, 50);
            });
            this.$watch('searchQuery', () => {
                this.buildOrgTree();
            });
        },

        async loadAllData() {
            this.isLoading = true;
            try {
                const [hierRes, orgRes] = await Promise.all([
                    fetch('/teams/api/hierarchy/'),
                    fetch('/teams/api/org-chart/')
                ]);
                
                if (hierRes.ok) this.hierarchyData = await hierRes.json();
                if (orgRes.ok) {
                    const orgData = await orgRes.json();
                    this.orgChartNodes = orgData.nodes || [];
                    this.buildOrgTree();
                }
            } catch (err) {
                console.error("Failed to load organization data:", err);
                this.showToast("Failed to load organization data.", "error");
            } finally {
                this.isLoading = false;
                if (window.lucide) setTimeout(lucide.createIcons, 50);
            }
        },

        buildOrgTree() {
            if (!this.orgChartNodes || this.orgChartNodes.length === 0) {
                this.orgTrees = [];
                this.unassignedUsers = [];
                return;
            }

            const nodeMap = {};
            const unassigned = [];

            this.orgChartNodes.forEach(node => {
                nodeMap[node.id] = {
                    ...node,
                    children: [],
                    _matchesSearch: this.isNodeMatchingSearch(node)
                };
                // General Managers are top-level executive roots and need not assign any reporting manager; they are never unassigned personnel
                const isGeneralManager = (node.role_code === 'GM' || node.tier_level === 1);
                if (!node.has_team && !node.parent_id && !isGeneralManager) {
                    unassigned.push(nodeMap[node.id]);
                }
            });

            const roots = [];

            this.orgChartNodes.forEach(node => {
                const current = nodeMap[node.id];
                if (node.parent_id && nodeMap[node.parent_id]) {
                    nodeMap[node.parent_id].children.push(current);
                } else if (node.has_team || node.tier_level <= 2 || node.role_code === 'GM') {
                    roots.push(current);
                }
            });

            this.orgTrees = roots;
            this.unassignedUsers = unassigned;
            
            this.$nextTick(() => {
                if (window.lucide) lucide.createIcons();
            });
        },

        isNodeMatchingSearch(node) {
            if (!this.searchQuery) return true;
            const q = this.searchQuery.toLowerCase();
            return (
                node.name.toLowerCase().includes(q) ||
                node.role.toLowerCase().includes(q) ||
                node.team_name.toLowerCase().includes(q) ||
                node.department_name.toLowerCase().includes(q)
            );
        },

        toggleNodeCollapse(nodeId) {
            this.collapsedNodes[nodeId] = !this.collapsedNodes[nodeId];
            this.$nextTick(() => {
                if (window.lucide) lucide.createIcons();
            });
        },

        isNodeCollapsed(nodeId) {
            return !!this.collapsedNodes[nodeId];
        },

        expandAll() {
            this.collapsedNodes = {};
            this.$nextTick(() => {
                if (window.lucide) lucide.createIcons();
            });
        },

        collapseAll() {
            const map = {};
            this.orgChartNodes.forEach(n => {
                map[n.id] = true;
            });
            this.collapsedNodes = map;
            this.$nextTick(() => {
                if (window.lucide) lucide.createIcons();
            });
        },

        zoomIn() {
            this.zoomLevel = Math.min(1.8, +(this.zoomLevel + 0.1).toFixed(2));
        },

        zoomOut() {
            this.zoomLevel = Math.max(0.4, +(this.zoomLevel - 0.1).toFixed(2));
        },

        resetZoom() {
            this.zoomLevel = 1.0;
        },

        openReportingModal(node) {
            if (node.role_code === 'GM' || node.tier_level === 1) {
                this.showToast("General Managers are top executive roots and need not assign any reporting manager.", "info");
                return;
            }
            this.reportingForm = {
                user_id: node.id,
                user_name: node.name,
                role_code: node.role_code || 'TM',
                current_manager_id: node.parent_id,
                new_manager_id: node.parent_id || ''
            };
            this.showReportingModal = true;
        },

        getValidManagersForRole(roleCode, targetUserId) {
            if (roleCode === 'GM') {
                // General Managers need not to assign any reporting manager
                return [];
            } else if (roleCode === 'MGR') {
                // Managers can only report to GMs
                return this.orgChartNodes.filter(n => n.id !== targetUserId && n.role_code === 'GM');
            } else if (roleCode === 'TM') {
                // Team Members report to Managers (or GMs)
                return this.orgChartNodes.filter(n => n.id !== targetUserId && (n.role_code === 'MGR' || n.role_code === 'GM'));
            } else {
                return [];
            }
        },

        async saveReportingLine() {
            if (!this.reportingForm.user_id) return;
            
            try {
                const res = await fetch('/teams/api/update-reporting/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({
                        user_id: this.reportingForm.user_id,
                        reporting_to_id: this.reportingForm.new_manager_id ? parseInt(this.reportingForm.new_manager_id) : null
                    })
                });

                const data = await res.json();
                if (res.ok && data.status === 'success') {
                    this.showToast(data.message || "Reporting line updated successfully!", "success");
                    this.showReportingModal = false;
                    await this.loadAllData();
                } else {
                    this.showToast(data.message || "Failed to update reporting line.", "error");
                }
            } catch (err) {
                console.error(err);
                this.showToast("Server error while updating reporting line.", "error");
            }
        },

        showToast(message, type = 'info') {
            this.toastMessage = message;
            this.toastType = type;
            this.showToastNotification = true;
            setTimeout(() => {
                this.showToastNotification = false;
            }, 3500);
        }
    };
};
