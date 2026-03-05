class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/50/4f/b77bd348f36a5b778815b1d37d19f59f007f8f8ab7046f3a8d0b8abf1742/agentops_mcp_server-0.2.0.tar.gz"
  sha256 "afb5a5b35819d52aed5cd45eec5a623fd48d9bd83978c09c392f7f559b62a40b"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
